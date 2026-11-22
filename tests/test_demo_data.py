"""The demonstration data script: everything through the services, once per organization."""

import importlib.util
from datetime import datetime, timedelta
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


def _next(weekday):
    day = datetime.now(demo.SP).date()
    return day + timedelta(days=(weekday - day.weekday()) % 7)


@pytest.mark.parametrize("weekday", [0, 5], ids=["weekday", "weekend"])
def test_demo_data_runs_once(clinic, weekday):
    set_up(clinic)
    today = _next(weekday)
    counts = run(clinic.org_a, clinic.a.admin, confirm=True, today=today)
    assert counts["professionals"] == 3 and counts["patients"] == 40
    assert counts["appointments"] >= 20 and counts["encounters"] == 10 and counts["charges"] == 15
    arrivals = 2 if weekday < 5 else 0
    assert counts["walk_ins"] == 20 + arrivals and counts["arrivals"] == arrivals
    with clinic.as_user(clinic.a.admin) as admin:
        assert len(PatientService().search(actor=admin, page_size=100).items) == 40
        assert len(FinanceService().charges(actor=admin, page_size=100).items) == 15
        scheduling = SchedulingService()
        kinds = {kind.code: kind for kind in scheduling.appointment_types(actor=admin)}
        assert kinds["convenio"].payment_kind == "insurance" and kinds["consulta"].payment_kind == "private"
        # The second schedule works by order of arrival in the afternoons, with the insurance kinds.
        walk_in = [
            period
            for schedule in scheduling.schedules(actor=admin)
            for period in scheduling.day_plan(
                actor=admin,
                schedule_id=schedule.sysid,
                start_date=today + timedelta(days=1),
                end_date=today + timedelta(days=14),
            )
            if period.mode == "walk_in"
        ]
        assert len({period.schedule_id for period in walk_in}) == 1
        assert sum(period.taken for period in walk_in) == counts["walk_ins"] - arrivals
        assert all(period.capacity == 12 and period.taken == 2 for period in walk_in)
        assert all(
            set(period.appointment_type_ids) == {kinds["convenio"].sysid, kinds["convenioretorno"].sysid}
            for period in walk_in
        )
        if arrivals:
            (session,) = scheduling.queue(actor=admin, schedule_id=walk_in[0].schedule_id, date=today)
            assert [entry.appointment.arrival_number for entry in session.waiting] == [2, 1]
            assert [entry.is_priority for entry in session.waiting] == [True, False]
    with pytest.raises(Refused):
        run(clinic.org_a, clinic.a.admin, confirm=True)
    with pytest.raises(Refused):
        run(clinic.org_a, clinic.a.admin, confirm=False)


def test_demo_data_refuses_production_settings(clinic, monkeypatch):
    monkeypatch.setattr(demo, "allowed", lambda: False)
    with pytest.raises(Refused):
        demo.run(clinic.org_a, clinic.a.admin, confirm=True)
