"""The demonstration data script: everything through the services, once per organization."""

import importlib.util
from pathlib import Path

import pytest

from applications.med_finance.service_api import FinanceService
from applications.med_patients.service_api import PatientService
from applications.med_records.service_api import RecordsService
from applications.med_scheduling.service_api import SchedulingService

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("demo_data", ROOT / "tools" / "demo_data.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)
Refused, fake_cpf, run = demo.Refused, demo.fake_cpf, demo.run


def test_fake_cpf_is_valid():
    import random

    from applications.med_patients.validators import valid_cpf

    rng = random.Random(1)  # noqa: S311 - test data
    assert all(valid_cpf(fake_cpf(rng)) for _ in range(50))


def set_up(clinic):
    side = clinic.a
    with clinic.as_user(side.admin) as admin:
        PatientService().setup(actor=admin, name="Pacientes", idempotency_key="p")
        SchedulingService().setup(actor=admin, practice_name="Consultório", idempotency_key="s")
        RecordsService().setup(actor=admin, idempotency_key="r")
        FinanceService().setup(actor=admin, idempotency_key="f")


def test_demo_data_runs_once(clinic):
    set_up(clinic)
    counts = run(clinic.org_a, clinic.a.admin, confirm=True)
    assert counts["professionals"] == 3 and counts["patients"] == 40
    assert counts["appointments"] >= 20 and counts["encounters"] == 10 and counts["charges"] == 15
    with clinic.as_user(clinic.a.admin) as admin:
        assert len(PatientService().search(actor=admin, page_size=100).items) == 40
        assert len(FinanceService().charges(actor=admin, page_size=100).items) == 15
    with pytest.raises(Refused):
        run(clinic.org_a, clinic.a.admin, confirm=True)
    with pytest.raises(Refused):
        run(clinic.org_a, clinic.a.admin, confirm=False)


def test_demo_data_refuses_production_settings(clinic, monkeypatch):
    monkeypatch.setattr(demo, "allowed", lambda: False)
    with pytest.raises(Refused):
        demo.run(clinic.org_a, clinic.a.admin, confirm=True)
