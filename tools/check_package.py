"""Confere o conteúdo de um .skapp: só arquivos do próprio pacote, sem os de desenvolvimento.

    python tools/check_package.py dist/med_patients.skapp med_patients

Usado pelo CI depois de `package build --git-ref HEAD` com uma chave descartável. Lê o
inventário do manifesto embutido (`files`) e falha se algum caminho for de desenvolvimento
(AGENTS.md, .gitattributes) ou pertencer a outra app da suíte.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import PurePosixPath

DEVELOPMENT = {"AGENTS.md", ".gitattributes", ".gitignore", "conftest.py", "pyproject.toml"}
SUITE = ("med_patients", "med_scheduling", "med_records", "med_finance")


def problems(paths: list[str], package: str) -> list[str]:
    found = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if PurePosixPath(path).name in DEVELOPMENT:
            found.append(f"development file in the package: {path}")
        if any(part in SUITE and part != package for part in parts):
            found.append(f"file of another app in the package: {path}")
        if parts and parts[0] in {"tools", ".github", ".claude"}:
            found.append(f"repository file in the package: {path}")
    if "LICENSE" not in {PurePosixPath(path).name for path in paths}:
        found.append("the package has no LICENSE")
    return found


def main(argv: list[str]) -> int:
    archive_path, package = argv
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    paths = [item["path"] for item in manifest["files"]]
    found = problems(paths, package)
    for line in found:
        print(line, file=sys.stderr)
    print(f"{package}: {len(paths)} files, {len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
