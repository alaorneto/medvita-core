"""The print rules of the apps hide only the navigation, never a document's own header or footer (#118)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STYLESHEETS = sorted(ROOT.glob("med_*/static/med_*/*.css"))
PRINT_BLOCK = re.compile(r"@media\s+print\s*\{(?P<body>(?:[^{}]*\{[^{}]*\})*[^{}]*)\}", re.S)
BARE_ELEMENT = re.compile(r"(?:^|[\s,>+~])(header|footer|nav|main|article|section)(?=\s*[,{:\[]|\s*$)")


def selectors(css: str) -> list[str]:
    found = []
    for block in PRINT_BLOCK.finditer(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        found += [rule.split("{")[0].strip() for rule in block.group("body").split("}") if "{" in rule]
    return found


def test_the_rule_finds_a_bare_element():
    assert any(BARE_ELEMENT.search(item) for item in selectors("@media print { header, .toolbar { display: none; } }"))
    assert not any(BARE_ELEMENT.search(item) for item in selectors("@media print { .app-header { display: none; } }"))


@pytest.mark.parametrize("path", STYLESHEETS, ids=lambda path: path.parent.name)
def test_print_hides_no_bare_element(path):
    bad = [item for item in selectors(path.read_text(encoding="utf-8")) if BARE_ELEMENT.search(item)]
    assert bad == [], f"{path.name}: {bad}"
