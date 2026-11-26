"""The standard-library tests can run without installing pytest."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from bibtex import parse_bib
from check_integrity import Audit, check_content, check_web
from fix_issues import apply_changes, fix_latex, plan_changes
from latex import inspect_table, line_at, read_metadata
from project import MANIFEST, manifest_data


class ParserTests(unittest.TestCase):
    def test_malformed_rows_and_positions(self):
        tex = "\\begin{tabular}{cc}\nA\n\\\\\nB & C & D \\\\\n\\end{tabular}"
        problems, specials = inspect_table(tex)
        self.assertEqual([line_at(tex, error.position) for error in problems], [2, 4])
        self.assertEqual(specials, [])

    def test_metadata_and_text_symbol_context(self):
        tex = (r"\caption[Breve]{Título \citep[ver][p. 2]{clave_1, clave_2}}\label{tab:x}" "\n"
               r"\begin{tabular}{cc} A_B & \textbf{A & B} $x_1$ \cite{clave_1} \end{tabular}")
        meta = read_metadata(tex)
        self.assertEqual(meta.caption, r"Título \citep[ver][p. 2]{clave_1, clave_2}")
        self.assertEqual([key for key, _ in meta.cites], ["clave_1", "clave_2", "clave_1"])
        errors, specials = inspect_table(tex)
        self.assertFalse(errors)
        self.assertEqual([tex[position] for position in specials], ["_", "&"])
        repaired, fixes = fix_latex(tex)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(inspect_table(repaired), ([], []))
        self.assertIn(r"$x_1$ \cite{clave_1}", repaired)

    def test_percent_repair_requires_structural_evidence(self):
        tex = "\\begin{tabular}{cc}\n85% & A \\\\\n\\end{tabular}"
        repaired, notes = fix_latex(tex)
        self.assertIn(r"85\%", repaired)
        self.assertEqual(notes[0][0], 2)
        self.assertEqual(inspect_table(repaired), ([], []))
        comment = "\\begin{tabular}{c}\n85% & comentario\n\\end{tabular}"
        self.assertEqual(fix_latex(comment), (comment, []))

    def test_bib_macros_and_error_recovery(self):
        text = ('@string{j = "Revista"}\n'
                '@article(a, title=j # " {A, B}", author={Ana}, year=2024)\n'
                '@article{b, title={abierto\n'
                '@article{c, title={Otro}, year=2025}')
        entries, problems = parse_bib(text)
        self.assertEqual([entry.key for entry in entries], ["a", "c"])
        self.assertEqual(entries[0].fields["title"], "Revista {A, B}")
        self.assertEqual(len(problems), 1)

    def test_cross_references_and_unused_bib_keys_include_lines(self):
        root = Path(".").resolve()
        table, bib = Path("data/tablas/a.tex"), Path("data/bib/a.bib")
        audit = Audit(root)
        sources = {
            table: ("\\label{tab:x}\n\\label{tab:x}\n\\begin{tabular}{c}\n"
                    "\\cite{ausente} \\ref{tab:otro}\n\\end{tabular}"),
            bib: "@article{sinUsar, author={A}, title={T}, year={2020}}",
        }
        check_content(audit, sources, [table], [bib])
        self.assertEqual([(item.level, item.line) for item in audit.issues],
                         [("error", 2), ("error", 4), ("error", 4), ("warning", 1)])
        self.assertIn("ausente", audit.issues[1].message)

    def test_web_reports_missing_routes_and_bad_html(self):
        audit = Audit(Path(".").resolve())
        files = {
            Path("index.html"): '<!doctype html>\n<div id="a"><span id="a"></div>\n<img src="missing.png">',
            Path("css/style.css"): '.example { background: url(./missing.svg); }',
            Path("js/app.js"): '// fetch("ignorado.json")\nfetch("missing.json");',
        }
        check_web(audit, files)
        errors = [(item.path.as_posix(), item.line, item.message) for item in audit.issues if item.level == "error"]
        self.assertEqual([line for _, line, text in errors if "Ruta local rota" in text], [3, 1, 2])
        self.assertTrue(any("ID HTML duplicado" in text for _, _, text in errors))
        self.assertTrue(any("sin cerrar" in text for _, _, text in errors))

    def test_plan_does_not_write_and_backups_match_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/tablas").mkdir(parents=True)
            (root / "data/bib").mkdir()
            table = root / "data/tablas/á tabla.tex"
            old = "\\begin{tabular}{c}\r\nA_B \\\\\r\n\\end{tabular}\r\n".encode("utf-16")
            table.write_bytes(old)
            bib = root / "data/bib/ejemplo.bib"
            reference = "@article{a, author={A}, title={T}, year=2000}"
            bib.write_text(reference + "\n" + reference, encoding="utf-8")
            changes = plan_changes(root)
            self.assertEqual(table.read_bytes(), old)
            self.assertFalse((root / "backup").exists())
            self.assertFalse((root / MANIFEST).exists())
            applied, errors = apply_changes(root, changes)
            self.assertFalse(errors)
            self.assertTrue(applied)
            self.assertEqual(next((root / "backup").glob("*/data/tablas/*.tex")).read_bytes(), old)
            self.assertEqual(bib.read_text(encoding="utf-8").count(reference), 1)
            self.assertIn(r"A\_B", table.read_text(encoding="utf-8"))
            self.assertEqual(manifest_data(root)[0]["tables"][0]["path"], "data/tablas/á tabla.tex")
            self.assertEqual(plan_changes(root), {})


if __name__ == "__main__":
    unittest.main()
