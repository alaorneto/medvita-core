"""One icon per concept and one concept per icon, across the suite and the core (#144)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")
TEMPLATES = sorted(path for app in APPS for path in (ROOT / app / "templates").rglob("*.html"))
CONCEPT_TAG = re.compile(r'\{%\s*med_icon\s+"([^"]+)"')
ACTION_TAG = re.compile(r'\{%\s*med_action_icon\s+"([^"]+)"')


def suite():
    from applications.med_patients.templatetags import med_icons

    return med_icons


def core_icons():
    from skeleton.web.icons import ACTION_ICONS, CONCEPT_ICONS

    return CONCEPT_ICONS, ACTION_ICONS


def one_to_one(mapping: dict[str, str]) -> list[str]:
    seen: dict[str, str] = {}
    shared = []
    for concept, icon in mapping.items():
        if icon in seen:
            shared.append(f"{seen[icon]} and {concept} share {icon}")
        seen[icon] = concept
    return shared


def unknown_in_templates(html: str, concepts, actions) -> list[str]:
    return [name for name in CONCEPT_TAG.findall(html) if name not in concepts] + [
        name for name in ACTION_TAG.findall(html) if name not in actions
    ]


def test_each_suite_concept_has_its_own_icon():
    assert one_to_one(suite().MED_CONCEPT_ICONS) == []


def test_the_suite_never_redraws_a_core_concept_or_icon():
    core_concepts, core_actions = core_icons()
    icons = suite()
    assert set(icons.MED_CONCEPT_ICONS) & set(core_concepts) == set()
    core_drawn = set(core_concepts.values()) | set(core_actions)
    assert set(icons.MED_CONCEPT_ICONS.values()) & core_drawn == set()
    assert icons.MED_ACTION_ICONS & core_drawn == set()
    assert set(icons.MED_CONCEPT_ICONS.values()) & icons.MED_ACTION_ICONS == set()
    # The core action icons the suite draws by name are the core's own.
    assert icons.CORE_ACTION_ICONS <= set(core_actions)


def known():
    core_concepts, _core_actions = core_icons()
    icons = suite()
    return set(icons.MED_CONCEPT_ICONS) | set(core_concepts), icons.MED_ACTION_ICONS | icons.CORE_ACTION_ICONS


def test_every_icon_has_its_shapes_and_no_shape_is_unused():
    icons = suite()
    used = set(icons.MED_CONCEPT_ICONS.values()) | icons.MED_ACTION_ICONS
    assert used == set(icons.ICON_SHAPES)
    assert all(icons.icon_markup(name).startswith("<svg aria-hidden") for name in used)
    assert icons.icon_markup("no-such-icon") == ""


def test_templates_name_concepts_the_map_knows():
    concepts, actions = known()
    problems = {}
    for path in TEMPLATES:
        found = unknown_in_templates(path.read_text(encoding="utf-8"), concepts, actions)
        if found:
            problems[path.relative_to(ROOT).as_posix()] = found
    assert problems == {}


def test_each_rule_catches_what_it_is_for():
    assert one_to_one({"a": "x", "b": "x"}) == ["a and b share x"]
    # A template that writes the icon instead of the concept is refused.
    assert unknown_in_templates('{% med_icon "stethoscope" %}', {"professional": "stethoscope"}, set()) == [
        "stethoscope"
    ]
    assert unknown_in_templates('{% med_action_icon "trash" %}', {}, {"printer"}) == ["trash"]
    assert unknown_in_templates('{% med_icon "professional" class="size-4" %}', {"professional": "x"}, set()) == []


def test_icons_held_in_data_name_known_concepts(skeleton_db):
    """Tabs, panels and appointment buttons carry a concept; the views' own maps too."""
    from applications.med_patients.extension import PATIENT_SECTIONS, SUMMARY_PANELS
    from applications.med_scheduling import views as scheduling_views
    from applications.med_scheduling.extension import _actions

    concepts, actions = known()
    held = {f"section {code}": item.icon for code, item in PATIENT_SECTIONS.all()}
    held |= {f"panel {code}": item.icon for code, item in SUMMARY_PANELS.all()}
    held |= {f"action {code}": item.icon for code, item in _actions.items()}
    held |= {f"schedule tab {code}": icon for code, icon in scheduling_views.SCHEDULE_TAB_ICONS.items()}
    assert {name: icon for name, icon in held.items() if icon and icon not in concepts} == {}
    for name, (concept, action) in scheduling_views.TRANSITION_ICONS.items():
        assert bool(concept) != bool(action), name
        assert concept in concepts or action in actions, name
    sections = dict(PATIENT_SECTIONS.all())
    suite_ones = [code for code in sections if not code.startswith("med_example")]
    assert all(sections[code].icon for code in suite_ones)


def test_one_tag_draws_suite_and_core_icons(skeleton_db):
    icons = suite()
    assert icons.med_icon("encounter", "size-4").startswith('<svg aria-hidden="true"')
    assert 'class="size-4"' in icons.med_icon("privacy", "size-4")
    assert "<path" in icons.med_action_icon("trash") and "<path" in icons.med_action_icon("printer")
    assert icons.med_icon("no-such-concept") == "" and icons.med_icon("") == ""
    assert icons.med_action_icon("cog") == ""  # A core icon outside CORE_ACTION_ICONS is refused.
