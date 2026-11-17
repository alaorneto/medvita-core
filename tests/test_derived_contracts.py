"""The core's derived access contract for the tables whose rows need a patient of another app.

The kit hands ``make_child`` only the anchor, so building the patient is done here, outside the
app packages: a test of the suite may write rows of any app directly in a fixture context, while
an app's own tests may only use the other apps' service APIs.
"""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from applications.med_patients.models import Patient, PatientRegistry
from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import acting_as, build_service_scenario

NUMBERS = count(1)


def _patient(organization, owner):
    registry = PatientRegistry(organization=organization, owner=owner, visibility="private", name=f"R{next(NUMBERS)}")
    registry.save()
    patient = Patient(organization=organization, registry=registry, code=f"P{next(NUMBERS):06d}", full_name="Maria")
    patient.save()
    return patient


def test_appointment_follows_the_schedule(skeleton_db):
    from applications.med_scheduling.models import Appointment, AppointmentType, Practice, Room, Schedule
    from skeleton.contrib.calendar.service_api import CalendarService

    for label in ("med_patients", "skeleton_calendar", "med_scheduling"):
        open_app(label)
    scenario = build_service_scenario(Appointment, slug="derived-appointment")
    calendars = {}
    for organization, admin in ((scenario.a, scenario.admin_a), (scenario.b, scenario.admin_b)):
        with acting_as(admin, organization) as actor:
            calendars[organization.pk] = (
                CalendarService()
                .create_shared_calendar(
                    actor=actor, name="Base", owner_user_id=admin.pk, timezone="UTC", idempotency_key="base"
                )
                .sysid
            )

    def make_schedule(*, organization, owner):
        practice = Practice(organization=organization, owner=owner, visibility="private", name=f"C{next(NUMBERS)}")
        practice.save()
        room = Room(organization=organization, practice=practice, name="Sala")
        room.save()
        schedule = Schedule(
            organization=organization,
            owner=owner,
            visibility="private",
            practice=practice,
            name="Agenda",
            room=room,
            calendar_id=calendars[organization.pk],
        )
        schedule.save()
        return schedule

    def make_appointment(schedule):
        kind = AppointmentType(
            organization=schedule.organization, practice=schedule.practice, code=f"t{next(NUMBERS)}", name="Consulta"
        )
        kind.save()
        start = datetime(2026, 5, 4, 12, tzinfo=UTC)
        row = Appointment(
            organization=schedule.organization,
            schedule=schedule,
            code=f"A{next(NUMBERS):07d}",
            patient=_patient(schedule.organization, schedule.owner),
            appointment_type=kind,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
        )
        row.save()
        return row

    assert_derived_access_contract(
        child_model=Appointment, make_anchor=make_schedule, make_child=make_appointment, scenario=scenario
    )


@pytest.mark.parametrize(
    "table",
    ["patientchart", "encounter", "encountersection", "allergy", "medication", "entrytemplate", "clinicaldocument"],
)
def test_records_tables_follow_the_archive(skeleton_db, table):
    from applications.med_records.models import (
        Allergy,
        Archive,
        ClinicalDocument,
        Encounter,
        EncounterSection,
        EntryTemplate,
        Medication,
        PatientChart,
    )

    for label in ("med_patients", "skeleton_calendar", "med_scheduling", "med_records"):
        open_app(label)
    models = {
        "patientchart": PatientChart,
        "encounter": Encounter,
        "encountersection": EncounterSection,
        "allergy": Allergy,
        "medication": Medication,
        "entrytemplate": EntryTemplate,
        "clinicaldocument": ClinicalDocument,
    }
    scenario = build_service_scenario(models[table], slug=f"derived-{table}")

    def make_archive(*, organization, owner):
        archive = Archive(organization=organization, owner=owner, visibility="private", name=f"Arq {next(NUMBERS)}")
        archive.save()
        return archive

    def make_chart(archive):
        chart = PatientChart(
            organization=archive.organization,
            archive=archive,
            patient=_patient(archive.organization, archive.owner),
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        chart.save()
        return chart

    def make_encounter(archive):
        chart = make_chart(archive)
        encounter = Encounter(
            organization=archive.organization,
            chart=chart,
            patient=chart.patient,
            code=f"E{next(NUMBERS):08d}",
            occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
            author=archive.owner,
        )
        encounter.save()
        return encounter

    def make_section(archive):
        section = EncounterSection(
            organization=archive.organization,
            encounter=make_encounter(archive),
            section_type="med_records.free_text",
            text="x",
        )
        section.save()
        return section

    def make_allergy(archive):
        row = Allergy(organization=archive.organization, chart=make_chart(archive), substance="Látex")
        row.save()
        return row

    def make_medication(archive):
        row = Medication(organization=archive.organization, chart=make_chart(archive), name="Losartana")
        row.save()
        return row

    def make_template(archive):
        row = EntryTemplate(organization=archive.organization, archive=archive, name="Modelo", kind="encounter")
        row.save()
        return row

    def make_document(archive):
        chart = make_chart(archive)
        row = ClinicalDocument(
            organization=archive.organization,
            chart=chart,
            patient=chart.patient,
            code=f"D{next(NUMBERS):08d}",
            kind="med_records.certificate",
            title="Atestado",
            author=archive.owner,
        )
        row.save()
        return row

    makers = {
        "patientchart": make_chart,
        "encounter": make_encounter,
        "encountersection": make_section,
        "allergy": make_allergy,
        "medication": make_medication,
        "entrytemplate": make_template,
        "clinicaldocument": make_document,
    }
    assert_derived_access_contract(
        child_model=models[table], make_anchor=make_archive, make_child=makers[table], scenario=scenario
    )
