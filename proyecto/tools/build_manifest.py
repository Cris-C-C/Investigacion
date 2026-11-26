"""Generate the static browser index from data/tablas and data/bib."""

import argparse
from pathlib import Path

from project import MANIFEST, ROOT, manifest_data, manifest_text, write_atomic


def main():
    parser = argparse.ArgumentParser(description="Genera data/manifest.json desde los archivos .tex y .bib.")
    parser.add_argument("--root", type=str, help="Raíz del proyecto (por defecto, el directorio que contiene tools).")
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else ROOT
    if not (root / "data").is_dir():
        print("Error: no existe el directorio data/.")
        return 1
    manifest, warnings = manifest_data(root)
    try:
        content = manifest_text(manifest).encode("utf-8")
        path = root / MANIFEST
        if not path.is_file() or path.read_bytes() != content:
            write_atomic(path, content)
    except OSError as error:
        print(f"Error al escribir {MANIFEST.as_posix()}: {error}")
        return 1
    print(f"{MANIFEST.as_posix()}: {len(manifest['tables'])} tablas, {len(manifest['bibliography'])} archivos BibTeX.")
    for path, message in warnings:
        print(f"Error al leer {path.as_posix()}: {message}")
    return int(bool(warnings))


if __name__ == "__main__":
    raise SystemExit(main())
