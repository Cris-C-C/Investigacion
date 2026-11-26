"""Audit LaTeX, BibTeX, the manifest and the static website."""

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

from bibtex import parse_bib
from latex import inspect_table, line_at, percent_candidates, read_metadata
from project import MANIFEST, REPORT, ROOT, data_files, manifest_data, read_text, write_atomic


@dataclass
class Issue:
    level: str
    path: Path
    line: int
    message: str
    suggestion: str = ""

    def format(self):
        message = f"{self.path.as_posix()}:{self.line} — {self.message}"
        return f"{message} {self.suggestion}" if self.suggestion else message


class Audit:
    def __init__(self, root):
        self.root = root
        self.issues = []
        self.summary = {}

    def add(self, level, path, line, message, suggestion=""):
        self.issues.append(Issue(level, path, line, message, suggestion))

    def error(self, path, line, message, suggestion=""):
        self.add("error", path, line, message, suggestion)

    def warning(self, path, line, message, suggestion=""):
        self.add("warning", path, line, message, suggestion)

    def read(self, path):
        try:
            text, encoding = read_text(self.root / path)
        except UnicodeDecodeError as error:
            original = (self.root / path).read_bytes()
            line = original.count(b"\n", 0, error.start) + 1
            self.error(path, line, f"Secuencia no válida para {error.encoding} en byte {error.start}.",
                       "Identifica la codificación de origen y guarda en UTF-8.")
            return None
        except (OSError, UnicodeError) as error:
            self.error(path, 1, f"No se pudo leer el archivo: {error}")
            return None
        if encoding != "utf-8":
            self.error(path, 1, f"Codificación {encoding}.", "Guarda en UTF-8 sin BOM.")
        unusual = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd\ufeff\u202a-\u202e\u2066-\u2069]"
        for match in re.finditer(unusual, text):
            self.warning(path, line_at(text, match.start()), f"Carácter inusual U+{ord(match[0]):04X}.")
        for match in re.finditer(r"Ã[¡©­³º±¼‰‘]|Â[ °±]|â[€™]", text):
            self.warning(path, line_at(text, match.start()), "Posible texto UTF-8 mal decodificado.",
                         "Comprueba el texto de origen.")
        return text


def check_content(audit, sources, tables, bibs):
    citations, refs = [], []
    labels, keys = {}, {}
    for path in tables:
        text = sources[path]
        if text is None:
            continue
        metadata = read_metadata(text)
        problems, specials = inspect_table(text)
        for problem in problems + metadata.problems:
            audit.error(path, line_at(text, problem.position), str(problem),
                        "Revisa la sintaxis de la tabla en esta línea.")
        for position in specials:
            char = text[position]
            escape = r"\textasciicircum{}" if char == "^" else "\\" + char
            audit.error(path, line_at(text, position), f"Carácter de texto sin escapar: {char}.",
                        f"Usa {escape} si se trata de texto literal.")
        for position in percent_candidates(text):
            audit.warning(path, line_at(text, position), "Un % tras un número comenta el resto de esta fila.",
                          r"Usa \% si querías mostrar el porcentaje.")
        for label, position in metadata.labels:
            line = line_at(text, position)
            if label in labels:
                old_path, old_line = labels[label]
                audit.error(path, line, f"Etiqueta duplicada {label} (primera en {old_path.as_posix()}:{old_line}).",
                            "Asigna una etiqueta única y actualiza sus referencias.")
            else:
                labels[label] = (path, line)
        citations.extend((key, path, line_at(text, position)) for key, position in metadata.cites)
        refs.extend((label, path, line_at(text, position)) for label, position in metadata.refs)

    for path in bibs:
        text = sources[path]
        if text is None:
            continue
        entries, problems = parse_bib(text)
        for problem in problems:
            audit.error(path, line_at(text, problem.position), str(problem),
                        "Revisa las llaves, las comas y las definiciones BibTeX.")
        for entry in entries:
            line = line_at(text, entry.start)
            if entry.key in keys:
                old_path, old_line = keys[entry.key]
                audit.error(path, line, f"Clave BibTeX duplicada {entry.key} (primera en {old_path.as_posix()}:{old_line}).",
                            "Conserva una sola entrada por clave o asigna claves distintas.")
            else:
                keys[entry.key] = (path, line)
            missing = [name for name in ("author", "title", "year")
                       if not entry.fields.get(name, "").strip(" \t\n\r{}")]
            if missing:
                audit.error(path, line, f"{entry.key} carece de campos obligatorios: {', '.join(missing)}.",
                            "Completa los campos a partir de la fuente.")
    for key, path, line in citations:
        if key not in keys:
            audit.error(path, line, f"Cita sin entrada BibTeX: {key}.",
                        "Verifica la clave o añade la entrada correspondiente.")
    for label, path, line in refs:
        if label not in labels:
            audit.error(path, line, f"Referencia cruzada sin etiqueta: {label}.",
                        "Comprueba la clave usada en \\ref y en \\label.")
    unused = sorted(keys.keys() - {key for key, _, _ in citations})
    for key in unused:
        path, line = keys[key]
        audit.warning(path, line, f"Clave BibTeX nunca citada: {key}.")
    audit.summary.update(tablas=len(tables), archivos_bib=len(bibs), claves_bib=len(keys), citas=len(citations))


def check_manifest(audit, sources):
    text = sources.get(MANIFEST)
    if text is None:
        return
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as error:
        audit.error(MANIFEST, error.lineno, "JSON inválido.", "Ejecuta tools/build_manifest.py.")
        return
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        audit.error(MANIFEST, 1, "Versión o formato no válido.", "Ejecuta tools/build_manifest.py.")
        return
    expected, _ = manifest_data(audit.root)

    def manifest_line(value):
        token = json.dumps(value, ensure_ascii=False)
        position = text.find(token)
        if position < 0:
            position = text.find(json.dumps(value))
        return line_at(text, max(0, position))

    for category in ("tables", "bibliography"):
        values = manifest.get(category)
        if not isinstance(values, list):
            audit.error(MANIFEST, 1, f"Falta una lista válida para {category}.")
            continue
        is_table = category == "tables"
        get_path = (lambda item: item.get("path") if isinstance(item, dict) else None) if is_table else (lambda item: item)
        required = {get_path(item): item for item in expected[category]}
        listed = set()
        for item in values:
            value = get_path(item)
            if not isinstance(value, str):
                audit.error(MANIFEST, 1, f"Entrada inválida en {category}.", "Regenera el manifiesto.")
                continue
            line = manifest_line(value)
            if value in listed:
                audit.error(MANIFEST, line, f"Ruta duplicada: {value}.")
            listed.add(value)
            if value not in required:
                audit.error(MANIFEST, line, f"Ruta ausente o inesperada: {value}.", "Regenera el manifiesto.")
            elif is_table and item != required[value]:
                audit.error(MANIFEST, line, f"Metadatos desactualizados: {value}.", "Regenera el manifiesto.")
        for missing in sorted(required.keys() - listed):
            audit.error(Path(missing), 1, "Archivo sin entrada en el manifiesto.", "Regenera el manifiesto.")


VOID = set("area base br col embed hr img input link meta param source track wbr".split())


class HTMLAudit(HTMLParser):
    def __init__(self, audit, path):
        super().__init__()
        self.audit = audit
        self.path = path
        self.stack = []
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        if tag not in VOID:
            self.stack.append((tag, line))
        for key, value in attrs:
            if key == "id":
                if not value or re.search(r"\s", value):
                    self.audit.error(self.path, line, f"ID HTML no válido: {value!r}.")
                if value in self.ids:
                    self.audit.error(self.path, line, f"ID HTML duplicado: {value}.")
                self.ids.add(value)
            if key in {"src", "href", "poster", "action", "data"} and value:
                self.links.append((value, line))
            if key == "srcset" and value and not value.startswith("data:"):
                self.links.extend((candidate.split()[0], line) for candidate in value.split(",") if candidate.strip())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.audit.error(self.path, self.getpos()[0], f"<{tag}/> requiere cierre explícito en HTML.")
            self.stack.pop()

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        if self.stack and tag == self.stack[-1][0]:
            self.stack.pop()
        else:
            self.audit.error(self.path, line, f"Cierre </{tag}> sin apertura correspondiente en ese punto.")
            if tag in [name for name, _ in self.stack]:
                while self.stack[-1][0] != tag:
                    name, start = self.stack.pop()
                    self.audit.error(self.path, start, f"Etiqueta <{name}> sin cerrar.")
                self.stack.pop()

    def finish(self):
        self.close()
        for tag, line in self.stack:
            self.audit.error(self.path, line, f"Etiqueta <{tag}> sin cerrar.")


def check_route(audit, path, line, value, base):
    try:
        url = urlsplit(value)
        if url.scheme or url.netloc or not url.path:
            return
        target = unquote(url.path)
        resolved = ((audit.root if target.startswith("/") else audit.root / base) / target.lstrip("/")).resolve()
        exists = resolved.is_file() or (resolved.is_dir() and (resolved / "index.html").is_file())
        if not resolved.is_relative_to(audit.root) or not exists:
            audit.error(path, line, f"Ruta local rota: {value}.", "Corrige la ruta o añade el archivo.")
    except (ValueError, OSError, RuntimeError):
        audit.error(path, line, f"Ruta local inválida: {value}.")


INLINE_QUOTED = r"""(["'\x60])([^"'\x60\r\n]+)\1"""
JS_IMPORT = re.compile(r"\b(?:import\s*\(\s*|import\s+|from\s+)" + INLINE_QUOTED)
JS_FETCH = re.compile(r"\bfetch\s*\(\s*" + INLINE_QUOTED)
JS_URL = re.compile(r"\bnew\s+URL\s*\(\s*" + INLINE_QUOTED + r"\s*,\s*import\.meta\.url")
CSS_PATH = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)|@import\s+(['"])([^'"]+)\3""", re.I)


def mask_comments(text, pattern):
    return re.sub(pattern, lambda match: "".join("\n" if char == "\n" else " " for char in match[0]), text)


def check_web(audit, sources):
    node = shutil.which("node")
    for path, text in sources.items():
        if text is None:
            continue
        if path.suffix == ".html":
            html = HTMLAudit(audit, path)
            html.feed(text)
            html.finish()
            if not re.search(r"(?i)<!doctype\s+html\s*>", text):
                audit.error(path, 1, "Falta el doctype HTML5.")
            for value, line in html.links:
                if value.startswith("#") and len(value) > 1 and unquote(value[1:]) not in html.ids:
                    audit.error(path, line, f"Ancla HTML rota: {value}.")
                check_route(audit, path, line, value, path.parent)
        elif path.suffix == ".css":
            css = mask_comments(text, r"/\*[\s\S]*?\*/")
            for match in CSS_PATH.finditer(css):
                check_route(audit, path, line_at(css, match.start()), (match[2] or match[4]).strip(), path.parent)
        elif path.parts[0] == "js" and path.suffix in {".js", ".mjs"}:
            if node:
                result = subprocess.run([node, "--input-type=module", "--check"], input=text, text=True,
                                        encoding="utf-8", errors="replace", capture_output=True, timeout=15)
                if result.returncode:
                    match = re.search(r"\[stdin\]:(\d+)", result.stderr)
                    failure = next((line for line in result.stderr.splitlines() if "SyntaxError:" in line), "Sintaxis JS inválida.")
                    audit.error(path, int(match[1]) if match else 1, failure)
            # Keep quoted strings while masking standalone comment literals.
            tokens = re.compile(r"""(["'\x60])(?:\\[\s\S]|(?!\1)[^\\])*\1|//[^\n]*|/\*[\s\S]*?\*/""")
            javascript = tokens.sub(lambda m: m[0] if m[1] else re.sub(r"[^\n]", " ", m[0]), text)
            for regex, base in ((JS_IMPORT, path.parent), (JS_URL, path.parent), (JS_FETCH, Path("."))):
                for match in regex.finditer(javascript):
                    value = match[2]
                    if regex is JS_IMPORT and not value.startswith(("./", "../", "/")):
                        continue
                    if "$" + "{" not in value:
                        check_route(audit, path, line_at(javascript, match.start()), value, base)
    if not node:
        audit.warning(Path("js"), 1, "Node no está disponible. Se omitió node --check.")


def project_text_paths(root, tables, bibs):
    paths = set(tables + bibs + [MANIFEST, Path("index.html"), Path("css/style.css"), Path("js/app.js"),
                Path("vendor/katex/katex.min.css"), Path("vendor/katex/katex.min.js"),
                Path("js/latex-parser.js"), Path("js/bib-parser.js"), Path("README.md"), Path("requirements.txt")])
    for directory in ("js", "css", "tools", "tests"):
        paths.update(path.relative_to(root) for path in (root / directory).rglob("*")
                     if path.is_file() and path.suffix in {".css", ".html", ".js", ".mjs", ".py"}
                     and path.resolve().is_relative_to(root))
    return sorted(paths)


def run_checks(root):
    audit = Audit(root)
    tables, bibs = data_files(root, "tablas", ".tex"), data_files(root, "bib", ".bib")
    for folder in (Path("data/tablas"), Path("data/bib")):
        if not (root / folder).is_dir():
            audit.error(folder, 1, "Directorio requerido ausente.")
    sources = {path: audit.read(path) for path in project_text_paths(root, tables, bibs)}
    check_content(audit, sources, tables, bibs)
    check_manifest(audit, sources)
    check_web(audit, sources)
    return audit


def report(audit, corrections=(), dry_run=False, smoke_status="Omitida. Usa --smoke para ejecutarla."):
    errors = [issue for issue in audit.issues if issue.level == "error"]
    warnings = [issue for issue in audit.issues if issue.level == "warning"]
    score = max(0, 100 - 10 * len(errors) - 2 * len(warnings))
    summary = audit.summary
    lines = ["# Informe de integridad", "", "## Resumen", "",
             f"- Tablas: {summary.get('tablas', 0)}",
             f"- Archivos BibTeX: {summary.get('archivos_bib', 0)}",
             f"- Claves BibTeX: {summary.get('claves_bib', 0)}",
             f"- Citas: {summary.get('citas', 0)}",
             f"- Errores: {len(errors)}",
             f"- Advertencias: {len(warnings)}",
             f"- Puntaje de integridad: {score}/100",
             f"- Prueba de humo: {smoke_status}",
             "", "Se descuentan 10 puntos por error y 2 por advertencia, con un mínimo de 0."]
    groups = (("Errores", [issue.format() for issue in errors]),
              ("Advertencias", [issue.format() for issue in warnings]),
              ("Correcciones propuestas" if dry_run else "Correcciones aplicadas", list(corrections)))
    for title, messages in groups:
        lines.extend(("", f"## {title}", ""))
        lines.extend(f"- {message}" for message in messages or ["Ninguna."])
    return "\n".join(lines) + "\n", int(bool(errors))


def emit_report(audit, corrections=(), dry_run=False, smoke_status="Omitida. Usa --smoke para ejecutarla."):
    content, status = report(audit, corrections, dry_run, smoke_status)
    print(content, end="")
    if not dry_run:
        try:
            path = audit.root / REPORT
            path.parent.mkdir(exist_ok=True)
            write_atomic(path, content.encode("utf-8"))
            print(f"\nInforme: {REPORT.as_posix()}")
        except OSError as error:
            print(f"Error al escribir el informe: {error}", file=sys.stderr)
            return 1
    return status


def main():
    parser = argparse.ArgumentParser(description="Verifica el proyecto y genera tools/report.md.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Raíz del proyecto.")
    parser.add_argument("--smoke", action="store_true", help="Prueba el sitio en Chromium mediante Playwright si está disponible.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    audit = run_checks(args.root.resolve())
    if args.smoke:
        from smoke import smoke_test
        return emit_report(audit, smoke_status=smoke_test(audit))
    return emit_report(audit)


if __name__ == "__main__":
    raise SystemExit(main())
