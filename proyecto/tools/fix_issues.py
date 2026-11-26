"""Plan and apply reversible corrections, then audit the resulting project."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import sys
import tempfile

from bibtex import parse_bib
from check_integrity import emit_report, project_text_paths, run_checks
from latex import inspect_table, line_at, percent_candidates
from project import MANIFEST, ROOT, data_files, manifest_data, manifest_text, read_text, write_atomic


@dataclass
class Change:
    before: bytes | None
    after: bytes
    notes: list = field(default_factory=list)


def fix_latex(text):
    notes = []
    errors, specials = inspect_table(text)
    # Only edit plain text detected by the scanner. Top-level & is a delimiter.
    if specials:
        for position in reversed(specials):
            if text[position] not in "_&":
                continue
            char = text[position]
            notes.append((line_at(text, position), f"Se escapó {char} en texto literal."))
            text = text[:position] + "\\" + text[position:]
    # A number followed by a comment that looks like a row delimiter is ambiguous
    # unless escaping it repairs a structural error without adding others.
    if errors:
        errors, _ = inspect_table(text)
        candidates = percent_candidates(text)
        for position in reversed(candidates):
            candidate = text[:position] + "\\" + text[position:]
            remaining, _ = inspect_table(candidate)
            line = line_at(text, position)
            old = {(line_at(text, error.position), str(error)) for error in errors}
            new = {(line_at(candidate, error.position), str(error)) for error in remaining}
            if new < old and any(problem_line == line for problem_line, _ in old - new):
                text = candidate
                errors = remaining
                notes.append((line, "Se escapó un porcentaje que ocultaba el separador de la fila."))
    return text, sorted(notes)


def normalize_data(text, path):
    new = text.replace("\r\n", "\n").replace("\r", "\n")
    notes = [(1, "Se normalizaron los saltos de línea.")] if new != text else []
    # Keep spacing inside BibTeX values and TeX verbatim environments.
    if path.suffix.lower() == ".tex" and not re.search(r"\\(?:verb|lstinline|begin\s*\{(?:verbatim|lstlisting|minted))\b", new):
        cleaned = re.sub(r"(?m)^[ \t]+(?=\n|$)", "", new)
        if cleaned != new:
            new = cleaned
            notes.append((1, "Se retiraron espacios en líneas vacías."))
    return new, notes


def deduplicate_bib(path, text, seen):
    entries, problems = parse_bib(text)
    if problems:
        return text, []
    spans, notes = [], []
    for entry in entries:
        original = seen.get((entry.key, entry.raw))
        if original and original[1].fields == entry.fields and (path == original[0] or not entry.uses_macros):
            spans.append((entry.start, entry.end))
            notes.append((line_at(text, entry.start), f"Se retiró la entrada BibTeX idéntica {entry.key}."))
        elif not original:
            seen[(entry.key, entry.raw)] = (path, entry)
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text, notes


def plan_changes(root):
    tables = data_files(root, "tablas", ".tex")
    bibs = data_files(root, "bib", ".bib")
    seen, overrides, changes = {}, {}, {}
    data = set(tables + bibs)
    for path in project_text_paths(root, tables, bibs):
        absolute = root / path
        if path == MANIFEST or not absolute.is_file() or absolute.is_symlink() or not absolute.resolve().is_relative_to(root):
            continue
        try:
            before = absolute.read_bytes()
            text, encoding = read_text(absolute)
        except (OSError, UnicodeError):
            continue
        notes = [(1, f"Se convirtió {encoding} a UTF-8 sin BOM.")] if encoding != "utf-8" else []
        if path in data:
            text, spacing = normalize_data(text, path)
            notes.extend(spacing)
            if path.suffix.lower() == ".tex":
                if not re.search(r"\\(?:verb|lstinline|begin\s*\{(?:verbatim|lstlisting|minted))\b", text):
                    text, details = fix_latex(text)
                    notes.extend(details)
                overrides[path] = text
            else:
                text, details = deduplicate_bib(path, text, seen)
                notes.extend(details)
        after = text.encode("utf-8")
        if before != after:
            changes[path] = Change(before, after, notes)
    if (root / "data").is_dir():
        manifest, _ = manifest_data(root, overrides)
        path = root / MANIFEST
        if not path.is_symlink() and path.resolve().is_relative_to(root):
            before = path.read_bytes() if path.is_file() else None
            after = manifest_text(manifest).encode("utf-8")
            if before != after:
                changes[MANIFEST] = Change(before, after, [(1, "Se regeneró el manifiesto.")])
    return changes


def backup_directory(root):
    base = root / "backup"
    if not base.resolve().is_relative_to(root):
        raise OSError("La carpeta de copias apunta fuera del proyecto.")
    base.mkdir(exist_ok=True)
    prefix = datetime.now().strftime("%Y%m%d-%H%M%S-")
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def describe(path, change):
    return [f"{path.as_posix()}:{line} — {note}" for line, note in change.notes]


def apply_changes(root, changes):
    if not changes:
        return [], []
    try:
        backup = backup_directory(root)
    except OSError as error:
        return [], [(Path("backup"), str(error))]
    applied, errors = [f"Copias de seguridad: {backup.relative_to(root).as_posix()}/."], []
    for path, change in changes.items():
        absolute = root / path
        try:
            if absolute.is_symlink() or not absolute.resolve().is_relative_to(root):
                raise OSError("La ruta de destino cambió desde la planificación.")
            current = absolute.read_bytes() if absolute.is_file() else None
            if current != change.before:
                raise OSError("El archivo cambió desde la planificación.")
            target = backup / path
            if current is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(current)
            else:
                with (backup / "archivos-nuevos.txt").open("a", encoding="utf-8") as handle:
                    handle.write(path.as_posix() + "\n")
            write_atomic(absolute, change.after)
            applied.extend(describe(path, change))
        except OSError as error:
            errors.append((path, str(error)))
    return applied, errors


def main():
    parser = argparse.ArgumentParser(description="Corrige problemas seguros y genera un informe de integridad.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Raíz del proyecto.")
    parser.add_argument("--dry-run", action="store_true", help="Muestra cambios y diagnóstico en consola sin escribir archivos.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = args.root.resolve()
    try:
        changes = plan_changes(root)
    except OSError as error:
        audit = run_checks(root)
        audit.error(MANIFEST, 1, f"No se pudo planificar la corrección: {error}")
        return emit_report(audit, dry_run=args.dry_run)
    if args.dry_run:
        proposed = [item for path, change in changes.items() for item in describe(path, change)]
        return emit_report(run_checks(root), proposed, dry_run=True)
    applied, errors = apply_changes(root, changes)
    audit = run_checks(root)
    for path, message in errors:
        audit.error(path, 1, f"No se pudo aplicar la corrección: {message}")
    return emit_report(audit, applied)


if __name__ == "__main__":
    raise SystemExit(main())
