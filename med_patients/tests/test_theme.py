"""The MedVita theme of the instance, shipped with the app (#65): valid for the core and brand-neutral CSS."""

import json
import re
from pathlib import Path

from skeleton.testing.appearance import assert_app_themes_valid

APP_DIR = Path(__file__).resolve().parents[1]
THEME = APP_DIR / "themes" / "medvita"


def test_the_core_accepts_the_theme():
    """Format, AA contrast of the brand colour, core range and the ``<app_id>.theme.<slug>`` id (E047)."""
    assert_app_themes_valid("med_patients")


def test_manifest_and_theme_agree():
    manifest = json.loads((APP_DIR / "manifest.json").read_text(encoding="utf-8"))
    theme = json.loads((THEME / "theme.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["instance_themes"] == [{"path": "themes/medvita", "slug": "medvita"}]
    assert theme["id"] == f"{manifest['app_id']}.theme.medvita"
    assert theme["version"] == manifest["version"]  # The release automation writes both.
    assert theme["compatibility"] == {"skeleton": manifest["compatibility"]["skeleton"]}
    assert theme["brand"]["product_name"] == "MedVita"


def test_the_css_leaves_the_brand_colour_to_the_core():
    """The brand tokens come from ``brand_color``; fixing them would hide a clinic's own colour."""
    css = (THEME / "theme.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    brand = {name for name in declared if re.match(r"--color-(cobalt-|brand|fg-brand|focus)", name)}
    assert brand == set()
    assert all(name.startswith(("--color-", "--shadow-", "--mv-")) for name in declared), sorted(declared)
