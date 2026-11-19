"""Fill an organization with fictitious demonstration data, only through the public services of the apps.

    python tools/demo_data.py --org <slug> --as <email of an administrator> --confirm

The four apps must be configured in the organization (the clinic setup list) and it must have no
patient yet. The administrator becomes the first professional and signs the encounters. The script
refuses to run outside the development and test settings (``DEBUG`` or a test settings module).
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

FIRST_NAMES = (
    "Ana", "Bruno", "Carla", "Daniel", "Elisa", "Fábio", "Gabriela", "Heitor", "Isabela", "João",
    "Karina", "Lucas", "Marina", "Nelson", "Olívia", "Paulo", "Queila", "Rafael", "Sofia", "Tiago",
)  # fmt: skip
LAST_NAMES = ("Almeida", "Barbosa", "Cardoso", "Duarte", "Esteves", "Ferraz", "Gomes", "Hora", "Lima", "Moura")
SP = ZoneInfo("America/Sao_Paulo")


class Refused(Exception):
    pass


def fake_cpf(rng: random.Random) -> str:
    """A CPF with valid check digits, random and fictitious."""
    numbers = [rng.randint(0, 9) for _ in range(9)]
    for size in (9, 10):
        total = sum(number * (size + 1 - index) for index, number in enumerate(numbers[:size]))
        numbers.append((total * 10) % 11 % 10)
    return "".join(map(str, numbers))


def allowed() -> bool:
    import os

    from django.conf import settings

    module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    return bool(settings.DEBUG) or "test" in module


def run(organization: Any, admin: Any, *, confirm: bool, seed: int = 7) -> dict[str, int]:
    """Create the demonstration data; returns what was created. Raises ``Refused`` when it must not run."""
    from applications.med_finance.service_api import ChargeItemInput, FinanceService
    from applications.med_patients.service_api import PatientInput, PatientService
    from applications.med_records.service_api import RecordsService
    from applications.med_scheduling.service_api import AvailabilityRuleInput, SchedulingService
    from skeleton.testing.service_api import acting_as

    if not allowed():
        raise Refused("Demonstration data only in development and test settings.")
    if not confirm:
        raise Refused("Pass --confirm to write the demonstration data.")
    rng = random.Random(seed)  # noqa: S311 - fictitious demonstration data, not a secret
    counts = {"professionals": 0, "patients": 0, "appointments": 0, "encounters": 0, "charges": 0}
    with acting_as(admin, organization, source="tools:demo-data") as actor:
        patients = PatientService()
        if patients.search(actor=actor, page_size=1).items:
            raise Refused("The organization already has patients.")
        scheduling = SchedulingService()
        doctor = scheduling.register_professional(
            actor=actor,
            display_name="Dra. Demonstração",
            council_number="100001",
            council_state="SP",
            membership_user_id=admin.pk,
            idempotency_key="demo-doctor-1",
        )
        others = [
            scheduling.register_professional(
                actor=actor,
                display_name=name,
                council_number=number,
                council_state="SP",
                idempotency_key=f"demo-doctor-{number}",
            )
            for name, number in (("Dr. Exemplo", "100002"), ("Dra. Fictícia", "100003"))
        ]
        counts["professionals"] = 3
        rooms = [scheduling.add_room(actor=actor, name=f"Sala {n}", idempotency_key=f"demo-room-{n}") for n in (1, 2)]
        kinds = [
            scheduling.add_appointment_type(
                actor=actor,
                code=code,
                name=name,
                duration_minutes=minutes,
                billing_code=code.upper(),
                idempotency_key=f"demo-kind-{code}",
            )
            for code, name, minutes in (
                ("consulta", "Consulta", 30),
                ("retorno", "Retorno", 20),
                ("primeira", "Primeira consulta", 60),
                ("procedimento", "Procedimento", 45),
            )
        ]
        schedules = []
        for index, professional in enumerate([doctor, *others]):
            schedule = scheduling.create_schedule(
                actor=actor,
                name=f"Agenda de {professional.display_name}",
                professional_id=professional.sysid,
                room_id=rooms[index % 2].sysid if index else None,
                idempotency_key=f"demo-schedule-{index}",
            )
            scheduling.set_availability(
                actor=actor,
                schedule_id=schedule.sysid,
                rules=tuple(AvailabilityRuleInput(day, 8 * 60, 12 * 60, datetime.now(SP).date()) for day in range(5)),
                expected_revision=schedule.revision,
            )
            schedules.append(schedule)
        finance = FinanceService()
        for kind, amount in zip(kinds, (25000, 12000, 35000, 40000), strict=True):
            finance.add_price_item(
                actor=actor,
                code=kind.billing_code,
                description=kind.name,
                amount=amount,
                idempotency_key=f"demo-price-{kind.code}",
            )
        people = []
        for number in range(40):
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"
            people.append(
                patients.create(
                    actor=actor,
                    data=PatientInput(
                        full_name=name,
                        cpf=fake_cpf(rng),
                        birth_date=date(1950 + rng.randint(0, 60), rng.randint(1, 12), rng.randint(1, 28)),
                        notes="Paciente fictício, dados de demonstração.",
                    ),
                    idempotency_key=f"demo-patient-{number}",
                )
            )
        counts["patients"] = len(people)
        booked = []
        start = datetime.now(SP).date() + timedelta(days=1)
        for offset in range(14):
            day = start + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            for hour in (8, 9, 10):
                patient = people[len(booked) % len(people)]
                schedule = schedules[len(booked) % len(schedules)]
                booked.append(
                    scheduling.book(
                        actor=actor,
                        schedule_id=schedule.sysid,
                        patient_id=patient.sysid,
                        appointment_type_id=kinds[0].sysid,
                        starts_at=datetime(day.year, day.month, day.day, hour, tzinfo=SP),
                        fit_in=True,
                        idempotency_key=f"demo-book-{day}-{hour}-{schedule.sysid}",
                    )
                )
        counts["appointments"] = len(booked)
        records = RecordsService()
        for number, patient in enumerate(people[:10]):
            chart = records.open_chart(actor=actor, patient_id=patient.sysid)
            draft = records.start_encounter(
                actor=actor, chart_id=chart.sysid, idempotency_key=f"demo-encounter-{number}"
            )
            draft = records.save_section(
                actor=actor,
                encounter_id=draft.header.sysid,
                section_type="med_records.free_text",
                text="Atendimento de demonstração, sem dado real.",
                expected_revision=draft.header.revision,
            )
            records.sign_encounter(
                actor=actor, encounter_id=draft.header.sysid, expected_revision=draft.header.revision
            )
            counts["encounters"] += 1
        for number, patient in enumerate(people[:15]):
            finance.create_charge(
                actor=actor,
                patient_id=patient.sysid,
                items=(ChargeItemInput(code=kinds[number % 4].billing_code),),
                idempotency_key=f"demo-charge-{number}",
            )
            counts["charges"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org", required=True, help="Slug of the organization.")
    parser.add_argument("--as", dest="email", required=True, help="Email of an administrator of the organization.")
    parser.add_argument("--confirm", action="store_true")
    arguments = parser.parse_args(argv)
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import transaction

    from skeleton.tenancy.context import system_context

    with system_context(reason="tools:demo-data"):
        from skeleton.tenancy.models import Organization

        organization = Organization.objects.get(slug=arguments.org)
        admin = get_user_model().objects.get(email=arguments.email)
    try:
        with transaction.atomic():
            counts = run(organization, admin, confirm=arguments.confirm)
    except Refused as error:
        print(error, file=sys.stderr)
        return 1
    print(", ".join(f"{value} {name}" for name, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
