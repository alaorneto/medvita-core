"""Imprime as variáveis de ambiente de desenvolvimento do sk_med_core.

    eval "$(python tools/devenv.py)"                        # bash, zsh
    python tools/devenv.py --powershell | Invoke-Expression  # PowerShell

As quatro apps entram por SKELETON_DEV_APPS, na ordem em que o Django as carrega; as first-party
do núcleo de que elas dependem entram por SKELETON_BUNDLED_APPS. Os caminhos são absolutos e
calculados a partir deste arquivo. O script nunca imprime senha: TEST_DATABASE_URL e
TEST_MIGRATION_DATABASE_URL vêm do ambiente ou do .env da raiz (ignorado pelo Git), e só
aparecem aqui como referência a si mesmos quando já estão definidos.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance", "tests/apps/med_example")
BUNDLED = ("calendar", "ledger")


def variables() -> dict[str, str]:
    return {
        "DJANGO_SETTINGS_MODULE": "skeleton.testing.host.settings",
        "SKELETON_DEV_APPS": ",".join((ROOT / app).as_posix() for app in APPS),
        "SKELETON_BUNDLED_APPS": ",".join(BUNDLED),
        "SKELETON_TEST_ALLOW_SCHEMA_RESET": "1",
    }


def render(values: dict[str, str], *, powershell: bool) -> str:
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'" if powershell else "'" + value.replace("'", "'\\''") + "'"

    lines = [
        f"$env:{name} = {quote(value)}" if powershell else f"export {name}={quote(value)}"
        for name, value in values.items()
    ]
    missing = [name for name in ("TEST_DATABASE_URL", "TEST_MIGRATION_DATABASE_URL") if not os.environ.get(name)]
    if missing and not (ROOT / ".env").is_file():
        lines.append(f"# defina {' e '.join(missing)} (veja docs/development.md)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--powershell", action="store_true", help="formato $env: do PowerShell")
    arguments = parser.parse_args(argv)
    print(render(variables(), powershell=arguments.powershell))
    return 0


if __name__ == "__main__":
    sys.exit(main())
