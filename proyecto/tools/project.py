"""Project paths, UTF-8 loading, manifest generation and atomic writes."""

import codecs
import json
from pathlib import Path
import os
import tempfile

from latex import read_metadata


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("data/manifest.json")
REPORT = Path("tools/report.md")
BOMS = ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"))


def data_files(root, folder, suffix):
    base = root / "data" / folder
    if not base.is_dir():
        return []
    return sorted((path.relative_to(root) for path in base.rglob("*")
                   if path.is_file() and path.suffix.lower() == suffix
                   and path.resolve().is_relative_to(base.resolve())), key=lambda path: path.as_posix())


def read_text(path):
    raw = path.read_bytes()
    encoding = next((name for marker, name in BOMS if raw.startswith(marker)), "utf-8")
    return raw.decode(encoding), encoding


def manifest_data(root, overrides=None):
    overrides = overrides or {}
    warnings = []
    tables = []
    for path in data_files(root, "tablas", ".tex"):
        try:
            text = overrides[path] if path in overrides else read_text(root / path)[0]
            metadata = read_metadata(text)
            table = {"path": path.as_posix(), "caption": metadata.caption,
                     "labels": list(dict.fromkeys(key for key, _ in metadata.labels)),
                     "citations": list(dict.fromkeys(key for key, _ in metadata.cites))}
        except (OSError, UnicodeError) as error:
            warnings.append((path, str(error)))
            table = {"path": path.as_posix(), "caption": "", "labels": [], "citations": []}
        tables.append(table)
    bibliography = [path.as_posix() for path in data_files(root, "bib", ".bib")]
    return {"version": 1, "tables": tables, "bibliography": bibliography}, warnings


def manifest_text(manifest):
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_atomic(path, content):
    """Replace only after the new file was successfully written."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
