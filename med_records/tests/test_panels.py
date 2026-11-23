"""Panels other apps add to a signed encounter and an issued document (registry)."""

import pytest

from ..extension import isolated_registries
from ..service_api import DocumentPanel, EncounterPanel, register_document_panel, register_encounter_panel


def test_codes_are_of_the_calling_app_and_unique():
    with isolated_registries():
        panel = EncounterPanel("med_records.extra", "Extra", template="med_records/_seal.html")
        assert register_encounter_panel(panel) is panel
        register_encounter_panel(panel)  # The same panel again is accepted.
        with pytest.raises(ValueError, match="already registered"):
            register_encounter_panel(EncounterPanel("med_records.extra", "Outro", url_name="med_records:home"))
        with pytest.raises(ValueError, match="<app_label>.<name>"):
            register_document_panel(DocumentPanel("extra", "Extra", url_name="med_records:home"))
        with pytest.raises(ValueError, match="cannot register"):
            register_document_panel(DocumentPanel("med_finance.extra", "Extra", url_name="med_records:home"))
        with pytest.raises(TypeError):
            register_document_panel(panel)


def test_a_panel_is_a_template_or_a_link():
    with pytest.raises(ValueError, match="not both"):
        EncounterPanel("med_records.extra", "Extra")
    with pytest.raises(ValueError, match="not both"):
        DocumentPanel("med_records.extra", "Extra", template="a.html", url_name="med_records:home")
    with pytest.raises(ValueError, match="callable"):
        DocumentPanel("med_records.extra", "Extra", url_name="med_records:home", context={"a": 1})
