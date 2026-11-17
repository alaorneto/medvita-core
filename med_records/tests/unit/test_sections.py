"""Validation of structured sections and the section type registry (no database)."""

import pytest

from skeleton.service_api import InvalidInput

from ...extension import SECTION_TYPES, SectionField, SectionType, isolated_registries, register_section_type
from ...sections import BASIC_TYPES, body_mass_index, validate_section

TYPES = {item.code: item for item in BASIC_TYPES}


def test_valid_data_is_normalized():
    data, text = validate_section(
        TYPES["med_records.vitals"],
        {"systolic": "120", "diastolic": 80, "temperature": "36,50", "weight": 70.0, "height": 175, "spo2": None},
        "",
    )
    assert data == {"systolic": 120, "diastolic": 80, "temperature": "36.5", "weight": "70", "height": 175}
    assert text == ""
    assert body_mass_index(data) == "22.9"


@pytest.mark.parametrize(
    ("code", "data"),
    [
        ("med_records.vitals", {"pulse": 80}),
        ("med_records.vitals", {"systolic": 400}),
        ("med_records.vitals", {"systolic": "abc"}),
        ("med_records.vitals", {"systolic": True}),
        ("med_records.vitals", {"temperature": "nan"}),
        ("med_records.anamnesis", {"chief_complaint": 12}),
        ("med_records.anamnesis", {"chief_complaint": "x" * 501}),
        ("med_records.assessment", {"diagnoses": [{"code": "J45", "primary": True}, {"code": "I10", "primary": True}]}),
        ("med_records.assessment", {"diagnoses": [{"code": "XYZ"}]}),
        ("med_records.assessment", {"diagnoses": [{"code": "J45", "note": "x"}]}),
    ],
)
def test_invalid_data_is_refused(code, data):
    with pytest.raises(InvalidInput):
        validate_section(TYPES[code], data, "")


def test_choice_required_date_and_free_text():
    kind = SectionType(
        "med_records.test_kind",
        "Teste",
        (
            SectionField("side", "Lado", "choice", required=True, choices=(("left", "Esquerdo"), ("right", "Direito"))),
            SectionField("on", "Data", "date"),
            SectionField("ok", "Sim", "boolean"),
        ),
        has_text=False,
    )
    assert validate_section(kind, {"side": "left", "on": "2026-01-02", "ok": "on"}) == (
        {"side": "left", "on": "2026-01-02", "ok": True},
        "",
    )
    for data in ({}, {"side": "up"}, {"side": "left", "on": "02/01/2026"}, {"side": "left", "ok": "maybe"}):
        with pytest.raises(InvalidInput):
            validate_section(kind, data)
    with pytest.raises(InvalidInput):
        validate_section(kind, {"side": "left"}, "texto")
    with pytest.raises(InvalidInput):
        validate_section(TYPES["med_records.free_text"], {}, "x" * 50_001)


def test_diagnoses_are_normalized():
    data, _text = validate_section(
        TYPES["med_records.assessment"],
        {"diagnoses": [{"code": "j45.0", "description": " Asma ", "primary": True}, {"code": "I10"}]},
    )
    assert data["diagnoses"] == [
        {"code": "J45.0", "description": "Asma", "primary": True},
        {"code": "I10", "description": "", "primary": False},
    ]


def test_registry_refuses_foreign_and_duplicated_codes():
    with isolated_registries():
        with pytest.raises(ValueError):
            register_section_type(SectionType("med_patients.x", "X"))
        with pytest.raises(ValueError):
            register_section_type(SectionType("bad code", "X"))
        with pytest.raises(ValueError):
            register_section_type(SectionType(TYPES["med_records.vitals"].code, "Outro", version=1))


def test_versions_live_side_by_side():
    with isolated_registries():
        old = SECTION_TYPES.get("med_records.free_text")
        newer = SectionType("med_records.free_text", "Texto livre v2", (SectionField("title", "Título", "text"),), 2)
        register_section_type(newer)
        assert SECTION_TYPES.get("med_records.free_text") == newer
        assert SECTION_TYPES.get("med_records.free_text", 1) == old
    assert SECTION_TYPES.get("med_records.free_text") == old
