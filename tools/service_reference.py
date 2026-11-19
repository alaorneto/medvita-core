"""Fill the "Serviços" and "DTOs" sections of an app's docs/service-api.md from its service_api.py.

    python tools/service_reference.py               # rewrite the four references
    python tools/service_reference.py --check       # exit 1 when a reference is out of date

Each app writes its own docs/service-api.md (overview, dependency, extension points, events,
version history) and leaves the generated part between the two markers below. Signatures,
summaries and the Autorização, Erros and Efeitos sections come from the docstrings of the
``@service_method`` methods; the DTO tables come from the dataclasses listed in ``__all__``.
Needs the development environment of docs/development.md (Django is set up).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import inspect
import json
import re
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- BEGIN GENERATED: tools/service_reference.py -->"
END = "<!-- END GENERATED -->"
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")


def _type(value: object) -> str:
    text = value if isinstance(value, str) else repr(value)
    if isinstance(value, type):
        text = value.__name__
    text = text.replace("typing.", "").replace("<class '", "").replace("'>", "")
    return re.sub(r"\b[\w]+\.(?=\w)", "", text)


def _section(doc: str, name: str) -> str:
    match = re.search(rf"{name}:(.*?)(?=\n\s*(?:Autorização|Erros|Efeitos):|\Z)", doc, re.S)
    return " ".join(match.group(1).split()) if match else ""


def _methods(service: type) -> list[str]:
    lines: list[str] = []
    for name, member in sorted(inspect.getmembers(service, callable)):
        if name.startswith("_") or not hasattr(member, "__wrapped__"):
            continue
        function = inspect.unwrap(member)
        signature = inspect.signature(function)
        params = []
        for parameter in list(signature.parameters.values())[1:]:
            text = parameter.name
            if parameter.default is not inspect.Parameter.empty:
                text += f"={parameter.default!r}"
            params.append(text)
        doc = inspect.getdoc(function) or ""
        summary = " ".join(doc.split("\n\n")[0].split())
        lines += [f"#### `{name}(*, {', '.join(params)}) -> {_type(signature.return_annotation)}`", "", summary, ""]
        for title in ("Autorização", "Erros", "Efeitos"):
            lines.append(f"- **{title}:** {_section(doc, title)}")
        lines.append("")
    return lines


def _dtos(module: object) -> list[str]:
    lines: list[str] = []
    for name in sorted(getattr(module, "__all__", ())):
        value = getattr(module, name, None)
        if not (isinstance(value, type) and dataclasses.is_dataclass(value)):
            continue
        hints = typing.get_type_hints(value)
        lines += [f"### `{name}`", ""]
        doc = inspect.getdoc(value) or ""
        if doc and not doc.startswith(f"{name}("):
            lines += [" ".join(doc.split("\n\n")[0].split()), ""]
        lines += ["| Campo | Tipo |", "|---|---|"]
        for field in dataclasses.fields(value):
            lines.append(f"| `{field.name}` | `{_type(hints.get(field.name, field.type))}` |")
        lines.append("")
    return lines


def generated(app: str) -> str:
    manifest = json.loads((ROOT / app / "manifest.json").read_text(encoding="utf-8"))
    module = importlib.import_module(manifest["runtime"]["service_api"]["module"])
    lines = [BEGIN, "", "## Serviços", ""]
    for class_name in manifest["runtime"]["service_api"]["classes"]:
        lines += [f"### `{class_name}`", ""] + _methods(getattr(module, class_name))
    lines += ["## DTOs", ""] + _dtos(module) + [END]
    return "\n".join(lines)


def rewrite(app: str, *, check: bool) -> bool:
    path = ROOT / app / "docs" / "service-api.md"
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{path}: the generated markers are missing.")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = head + generated(app) + tail
    if new == text:
        return True
    if not check:
        path.write_text(new, encoding="utf-8", newline="\n")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("apps", nargs="*", default=APPS)
    arguments = parser.parse_args(argv)
    import django

    django.setup()
    stale = []
    for app in arguments.apps:
        if not (ROOT / app / "docs" / "service-api.md").is_file():
            continue
        text = (ROOT / app / "docs" / "service-api.md").read_text(encoding="utf-8")
        if BEGIN not in text:
            continue
        if not rewrite(app, check=arguments.check):
            stale.append(app)
    if stale and arguments.check:
        print("out of date: " + ", ".join(stale) + " (run python tools/service_reference.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
