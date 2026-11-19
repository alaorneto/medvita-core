"""The closing keywords read by tools/close_stacked_issues.py (no database, no network)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("close_stacked_issues", ROOT / "tools" / "close_stacked_issues.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def test_closing_keywords():
    body = """## Issues
Closes #1
fixes: #2
Resolved #3
closes #1
Refs #4
Parte de #5 e ver alaorneto/skeleton#6.
Fix #7, resolves #8
"""
    assert script.closing_references(body) == [1, 2, 3, 7, 8]


def test_empty_body():
    assert script.closing_references("") == []
    assert script.closing_references(None) == []
