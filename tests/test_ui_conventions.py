"""The interface rules of the core and of AGENTS.md, checked on the templates and CSS of the four apps (#125).

The core checks its own templates (test_ui_vocabulary, test_table_stack, test_template_dates); these
scans do the same for the suite, so a new screen cannot bring back a hand-written badge, a table
that scrolls the page sideways, a fixed date format, a red action painted neutral or a hard colour.
Each rule has a negative case below that makes it fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")
TEMPLATES = sorted(path for app in APPS for path in (ROOT / app / "templates").rglob("*.html"))
STYLESHEETS = sorted(path for app in APPS for path in (ROOT / app / "static").rglob("*.css"))

# Shapes the core components own: never written by hand in an app template.
HAND_WRITTEN = {
    "badge": re.compile(r'class="badge\b'),
    "alert": re.compile(r'class="alert\b'),
    "empty-state": re.compile(r'class="empty-state\b'),
    "error-summary": re.compile(r'class="error-summary\b'),
}
FIXED_DATE = re.compile(r"\|\s*(?:date|time)\s*:\s*[\"']")
TABLE_DIV = re.compile(r'<div class="(?P<classes>table-scroll[^"]*)"')
SCROLL_ONLY = re.compile(r"\{#\s*table-scroll only:\s*\S[^#]*#\}\s*$")
CELL = re.compile(r"<td\b[^>]*>")
DESTRUCTIVE = re.compile(
    r'class="btn btn-(?:primary|secondary|ghost)\b[^"]*"[^>]*>\s*(?:\{%\s*translate\s*")?'
    r"(?:Remover|Revogar|Excluir|Desativar|Descartar|Anular|Estornar|Encerrar|Cancelar a|Cancelar o)"
)
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def hand_written(html: str) -> list[str]:
    return [name for name, pattern in HAND_WRITTEN.items() if pattern.search(html)]


def fixed_dates(html: str) -> list[str]:
    return FIXED_DATE.findall(html)


def tables_without_stack(html: str) -> list[str]:
    """Tables that would scroll the page on a phone: neither ``table-stack`` nor a declared reason."""
    found = []
    for match in TABLE_DIV.finditer(html):
        if "table-stack" in match.group("classes").split():
            continue
        if not SCROLL_ONLY.search(html[: match.start()].rstrip()):
            found.append(match.group(0))
    return found


def cells_without_label(html: str) -> list[str]:
    """Cells of a stacked table without ``data-label`` (the label each cell shows on a phone)."""
    missing = []
    for match in TABLE_DIV.finditer(html):
        if "table-stack" not in match.group("classes").split():
            continue
        end = html.find("</table>", match.end())
        missing += [cell for cell in CELL.findall(html[match.end() : end]) if "data-label=" not in cell]
    return missing


def destructive_in_neutral(html: str) -> list[str]:
    return DESTRUCTIVE.findall(html)


def hard_colours(css: str) -> list[str]:
    return HEX.findall(COMMENT.sub("", css))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("path", TEMPLATES, ids=relative)
def test_templates_follow_the_interface_rules(path):
    html = path.read_text(encoding="utf-8")
    problems = {
        "componente escrito à mão": hand_written(html),
        "data com formato fixo (use |moment)": fixed_dates(html),
        "tabela sem table-stack nem motivo": tables_without_stack(html),
        "célula sem data-label": cells_without_label(html),
        "ação destrutiva com cor neutra": destructive_in_neutral(html),
    }
    assert {rule: found for rule, found in problems.items() if found} == {}


@pytest.mark.parametrize("path", STYLESHEETS, ids=relative)
def test_app_css_uses_only_tokens(path):
    assert hard_colours(path.read_text(encoding="utf-8")) == []


def test_each_rule_catches_what_it_is_for():
    assert hand_written('<span class="badge badge-warning">x</span>') == ["badge"]
    assert hand_written('<div class="alert alert-warning">') == ["alert"]
    assert hand_written('<div class="empty-state">') == ["empty-state"]
    assert hand_written('{{ "pending"|status_badge:label }}') == []
    assert fixed_dates('{{ when|date:"d/m/Y" }} {{ at|time:"H:i" }}') == ['|date:"', '|time:"']
    assert fixed_dates("{{ when|moment:'date' }}") == []
    assert tables_without_stack('<div class="table-scroll"><table></table></div>') != []
    assert tables_without_stack('{# table-scroll only: dense report #}\n<div class="table-scroll"><table>') == []
    assert tables_without_stack('{# table-scroll only: #}<div class="table-scroll"><table>') != []  # A reason is due.
    assert tables_without_stack('<div class="table-scroll table-stack"><table>') == []
    stacked = '<div class="table-scroll table-stack"><table><tr><td>x</td><td data-label="Nome">y</td></tr></table>'
    assert cells_without_label(stacked) == ["<td>"]
    assert destructive_in_neutral('<button class="btn btn-secondary">{% translate "Remover" %}</button>') != []
    assert destructive_in_neutral('<a class="btn btn-danger-outline btn-sm" href="x">Remover</a>') == []
    assert hard_colours(".x { color: #dc2626; } /* #124 */") == ["#dc2626"]
    assert hard_colours(".x { color: var(--color-fg-danger); } /* issue #124 */") == []
