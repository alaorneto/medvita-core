"""The Medvita theme of the instance, shipped with the app (#65): valid for the core and brand-neutral CSS."""

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
    assert theme["brand"]["product_name"] == "Medvita"


def test_the_css_leaves_the_brand_colour_to_the_core():
    """The brand tokens come from ``brand_color``; fixing them would hide a clinic's own colour."""
    css = (THEME / "theme.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    brand = {name for name in declared if re.match(r"--color-(cobalt-|brand|fg-brand|focus)", name)}
    assert brand == set()
    assert all(name.startswith(("--color-", "--shadow-", "--mv-")) for name in declared), sorted(declared)


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def _contrast(first: str, second: str) -> float:
    def luminance(colour: str) -> float:
        channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_and_fills_pass_aa_in_light_and_dark():
    """The pairs the screens use pass WCAG AA in both schemes (#124): white on a danger fill, red and grey text."""
    css = THEME.joinpath("theme.css").read_text(encoding="utf-8")
    light_block, dark_block = css.split("@media (prefers-color-scheme: dark)", 1)
    light = _tokens(light_block)
    dark = {**light, **_tokens(dark_block)}
    for name, tokens in (("claro", light), ("escuro", dark)):
        card = tokens["--color-neutral-primary-soft"]
        pairs = {
            "branco sobre o botão de perigo": ("#ffffff", tokens["--color-danger"]),
            "texto de perigo no cartão": (tokens["--color-fg-danger"], card),
            "texto secundário no fundo": (tokens["--color-body-subtle"], tokens["--color-canvas"]),
            "texto de atenção no fundo de atenção": (tokens["--color-fg-warning"], tokens["--color-warning-soft"]),
        }
        for label, (text, background) in pairs.items():
            assert _contrast(text, background) >= 4.5, (name, label, text, background)


def test_the_body_uses_the_core_ibm_plex_sans():
    """The body font is the core's IBM Plex Sans (#126): the default token, no font file of its own for it."""
    manifest = json.loads(THEME.joinpath("theme.json").read_text(encoding="utf-8"))
    assert manifest["tokens"]["font"] == "default" and manifest["tokens"]["font_family"] == ""
    assert manifest["fonts"] == []  # One family (DESIGN.md): headings are IBM Plex Sans 600 too (#128).
    css = THEME.joinpath("theme.css").read_text(encoding="utf-8")
    assert "Inter" not in css and "Poppins" not in css and "--mv-font-display" not in css
