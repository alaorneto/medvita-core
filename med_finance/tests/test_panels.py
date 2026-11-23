"""Panels other apps add to the charge and the receipt page (registry and service)."""

import pytest

from ..extension import isolated_panels
from ..service_api import (
    ChargeItemInput,
    ChargePanel,
    FinanceService,
    ReceiptPanel,
    register_charge_panel,
    register_receipt_panel,
)
from .helpers import add_price, new_patient, prepare


def _never(**_target):
    raise RuntimeError("boom")


def test_codes_are_of_the_calling_app_and_unique():
    with isolated_panels():
        panel = ChargePanel("med_finance.extra", "Extra", template="med_finance/empty.html")
        assert register_charge_panel(panel) is panel
        register_charge_panel(panel)  # The same panel again is accepted.
        with pytest.raises(ValueError, match="already registered"):
            register_charge_panel(ChargePanel("med_finance.extra", "Outro", template="med_finance/empty.html"))
        with pytest.raises(ValueError, match="<app_label>.<name>"):
            register_charge_panel(ChargePanel("extra", "Extra", template="med_finance/empty.html"))
        with pytest.raises(ValueError, match="cannot register"):
            register_receipt_panel(ReceiptPanel("med_records.extra", "Extra", url_name="med_finance:desk"))
        with pytest.raises(TypeError):
            register_receipt_panel(panel)


def test_a_panel_is_a_template_or_a_link():
    with pytest.raises(ValueError, match="not both"):
        ChargePanel("med_finance.extra", "Extra")
    with pytest.raises(ValueError, match="not both"):
        ChargePanel("med_finance.extra", "Extra", template="a.html", url_name="med_finance:desk")
    with pytest.raises(ValueError, match="callable"):
        ReceiptPanel("med_finance.extra", "Extra", url_name="med_finance:desk", visible=True)


def test_visible_and_context_decide_what_shows(clinic):
    prepare(clinic)
    add_price(clinic, "C1", 25000)
    patient = new_patient(clinic)
    with clinic.as_user(clinic.a.reception) as actor:
        charge = (
            FinanceService()
            .create_charge(
                actor=actor, patient_id=patient.sysid, items=(ChargeItemInput(code="C1"),), idempotency_key="c"
            )
            .charge
        )
    seen = []

    def shown(*, actor, charge_id):
        seen.append(charge_id)
        return True

    with isolated_panels():
        register_charge_panel(
            ChargePanel(
                "med_finance.b_shown",
                "Mostrado",
                template="med_finance/empty.html",
                order=20,
                visible=shown,
                context=lambda *, actor, charge_id: {"z": 1, "a": 2},
            )
        )
        register_charge_panel(ChargePanel("med_finance.a_first", "Primeiro", url_name="med_finance:charge", order=10))
        register_charge_panel(
            ChargePanel(
                "med_finance.hidden", "Escondido", url_name="med_finance:charge", visible=lambda **_target: False
            )
        )
        register_charge_panel(
            ChargePanel("med_finance.broken", "Quebrado", url_name="med_finance:charge", visible=_never)
        )
        register_charge_panel(ChargePanel("med_finance.no_data", "Sem dados", template="x.html", context=_never))
        with clinic.as_user(clinic.a.reception) as actor:
            panels = FinanceService().charge_panels(actor=actor, charge_id=charge.sysid)
        with clinic.as_user(clinic.a.doctor) as doctor, pytest.raises(Exception) as error:
            FinanceService().charge_panels(actor=doctor, charge_id=charge.sysid)
        with clinic.as_user(clinic.b.reception, clinic.org_b) as outsider, pytest.raises(Exception) as other:
            FinanceService().charge_panels(actor=outsider, charge_id=charge.sysid)
    assert [panel.code for panel in panels] == ["med_finance.a_first", "med_finance.b_shown"]
    assert panels[1].context == (("a", 2), ("z", 1)) and panels[1].label == "Mostrado"
    assert seen == [charge.sysid]
    assert type(error.value).__name__ == "NotFound" and type(other.value).__name__ == "NotFound"
