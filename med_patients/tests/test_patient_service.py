"""PatientService: reading, searching and the commands, with the contract of the core kit."""

from datetime import date
from uuid import uuid4

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.events import capture_events
from skeleton.testing.service_api import (
    assert_cas_conflict,
    assert_denied_as_not_found,
    assert_rejects_other_actor,
    assert_tenant_isolated,
    assert_unavailable_when_disabled,
)

from ..service_api import PatientInput, PatientService
from .helpers import new_patient, setup_registry

CPF = "52998224725"


@pytest.fixture
def ready(clinic):
    setup_registry(clinic)
    setup_registry(clinic, clinic.b)
    return clinic


def service():
    return PatientService()


def test_create_numbers_validates_and_publishes(ready):
    with capture_events() as events:
        first = new_patient(ready, full_name="João da Silva", cpf="529.982.247-25", phone="(11) 98888-7777")
        second = new_patient(ready, full_name="Ana Souza")
    assert (first.code, second.code) == ("P000001", "P000002")
    assert (first.cpf, first.phone, first.display_name) == (CPF, "11988887777", "João da Silva")
    assert [event.event_type for event in events] == ["med_patients.patient_created"] * 2
    payload = dict(events[0].data)
    assert set(payload) == {"code", "status", "registry"}
    assert not {"João da Silva", CPF, "11988887777"} & {str(value) for value in payload.values()}


def test_create_reports_the_field_never_the_value(ready, subtests):
    for field, value in (("cpf", "11111111111"), ("national_health_card", "123"), ("birth_date", date(2999, 1, 1))):
        with subtests.test(field), pytest.raises(InvalidInput) as error:
            new_patient(ready, **{field: value})
        assert set(error.value.errors) == {field}
        assert str(value) not in " ".join(message for messages in error.value.errors.values() for message in messages)
    with subtests.test("no full name"), pytest.raises(InvalidInput):
        new_patient(ready, full_name=" ")


def test_cpf_is_unique_among_live_patients_of_the_organization(ready):
    first = new_patient(ready, cpf=CPF)
    with pytest.raises(Conflict):
        new_patient(ready, full_name="Outra", cpf=CPF)
    new_patient(ready, ready.b, full_name="Na outra clínica", cpf=CPF)
    with ready.as_user(ready.a.reception) as actor:
        service().delete(actor=actor, patient_id=first.sysid, expected_revision=first.revision)
    assert new_patient(ready, full_name="Agora pode", cpf=CPF).cpf == CPF


def test_create_is_idempotent(ready):
    with ready.as_user(ready.a.reception) as actor:
        one = service().create(actor=actor, data=PatientInput(full_name="Maria"), idempotency_key="form-1")
        two = service().create(actor=actor, data=PatientInput(full_name="Maria"), idempotency_key="form-1")
        assert one.sysid == two.sysid and one.code == two.code
        assert service().search(actor=actor).items == (service().summary(actor=actor, patient_id=one.sysid),)


def test_search_by_name_cpf_code_and_phone(ready, subtests):
    joao = new_patient(ready, full_name="João Pereira", cpf=CPF, phone="11988887777")
    new_patient(ready, full_name="Ana Pereira", social_name="Aninha")
    with ready.as_user(ready.a.finance) as actor:
        for query, expected in (
            ("joao", ["João Pereira"]),
            ("pereira", ["Ana Pereira", "João Pereira"]),
            ("aninha", ["Ana Pereira"]),
            ("529.982.247-25", ["João Pereira"]),
            (joao.code.lower(), ["João Pereira"]),
            ("98888-7777", ["João Pereira"]),
            ("ninguém", []),
        ):
            with subtests.test(query=query):
                found = service().search(actor=actor, query=query).items
                assert [item.display_name for item in found] == [
                    "Aninha" if name == "Ana Pereira" else name for name in expected
                ]


def test_search_pages_are_stable(ready):
    for index in range(7):
        new_patient(ready, full_name=f"Paciente {index}")
    with ready.as_user(ready.a.reception) as actor:
        seen, cursor = [], None
        while True:
            page = service().search(actor=actor, page_size=3, cursor=cursor)
            seen += [item.code for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break
    assert len(seen) == len(set(seen)) == 7


def test_reading_is_authorized_and_isolated(ready, subtests):
    own = new_patient(ready, full_name="Própria")
    foreign = new_patient(ready, ready.b, full_name="Estrangeira Única", cpf=CPF)
    markers = [foreign.sysid, "Estrangeira Única", CPF]  # Codes repeat across organizations.
    reception = ready.a.reception
    with subtests.test("authorized"), ready.as_user(reception) as actor:
        assert service().get(actor=actor, patient_id=own.sysid).writable
    with subtests.test("finance only reads"), ready.as_user(ready.a.finance) as actor:
        assert not service().get(actor=actor, patient_id=own.sysid).writable
    with subtests.test("A/B"):
        assert_tenant_isolated(ready.caller(lambda actor: service().search(actor=actor), reception), foreign=markers)
        assert_denied_as_not_found(
            ready.caller(lambda actor: service().get(actor=actor, patient_id=foreign.sysid), reception),
            missing=ready.caller(lambda actor: service().get(actor=actor, patient_id=uuid4()), reception),
        )
    with subtests.test("summaries leave out what is not readable"), ready.as_user(reception) as actor:
        found = service().summaries(actor=actor, patient_ids=(foreign.sysid, own.sysid, uuid4()))
        assert [item.sysid for item in found] == [own.sysid]
    with subtests.test("duplicates"), ready.as_user(reception) as actor:
        assert service().find_duplicates(actor=actor, cpf=CPF) == ()
    with subtests.test("app disabled"):
        assert_unavailable_when_disabled(
            ready.caller(lambda actor: service().search(actor=actor), reception),
            disabled=lambda: ready.app_disabled("med_patients"),
        )
    with subtests.test("other actor"), ready.as_user(reception):
        assert_rejects_other_actor(lambda: service().search(actor=ready.a.doctor))


def test_default_deny_without_a_grant_on_the_registry(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.admin) as admin:
        from skeleton.service_api.access import AccessService

        AccessService().revoke_record_access(
            actor=admin,
            table_key="med_patients.patientregistry",
            record_id=patient.registry_id,
            action="read",
            group_id=ready.a.groups["finance"],
        )
    with ready.as_user(ready.a.finance) as actor:
        assert service().search(actor=actor).items == ()
        with pytest.raises(NotFound):
            service().get(actor=actor, patient_id=patient.sysid)


def test_update_with_cas_and_only_real_changes(ready):
    patient = new_patient(ready, full_name="Carlos")
    calls = []

    def change(name):
        def call():
            with ready.as_user(ready.a.reception) as actor:
                calls.append(name)
                return service().update(
                    actor=actor, patient_id=patient.sysid, changes=(("social_name", name),), expected_revision=1
                )

        return call

    def reread():
        with ready.as_user(ready.a.reception) as actor:
            return service().get(actor=actor, patient_id=patient.sysid)

    updated = assert_cas_conflict(change("Cacá"), change("Carlinhos"), reread=reread)
    assert updated.display_name == "Cacá" and updated.revision == 2
    with ready.as_user(ready.a.reception) as actor, capture_events() as events:
        same = service().update(
            actor=actor, patient_id=patient.sysid, changes=(("social_name", "Cacá"),), expected_revision=2
        )
        assert same.revision == 2 and events == []
        assert service().search(actor=actor, query="caca").items[0].sysid == patient.sysid


def test_update_refuses_fields_outside_the_allowlist(ready, subtests):
    patient = new_patient(ready)
    for field in ("code", "registry", "status", "processing_restricted", "anonymized_at", "organization"):
        with subtests.test(field), ready.as_user(ready.a.reception) as actor, pytest.raises(InvalidInput):
            service().update(actor=actor, patient_id=patient.sysid, changes=((field, "x"),), expected_revision=1)


def test_finance_reads_but_does_not_write(ready):
    patient = new_patient(ready)
    with ready.as_user(ready.a.finance) as actor:
        with pytest.raises(Forbidden):
            service().update(actor=actor, patient_id=patient.sysid, changes=(("city", "X"),), expected_revision=1)
        with pytest.raises(Forbidden):
            service().create(actor=actor, data=PatientInput(full_name="X"))


def test_status_delete_and_restore(ready):
    patient = new_patient(ready, cpf=CPF)
    with ready.as_user(ready.a.reception) as actor, capture_events() as events:
        with pytest.raises(InvalidInput):
            service().set_status(actor=actor, patient_id=patient.sysid, status="deceased", expected_revision=1)
        dead = service().set_status(
            actor=actor, patient_id=patient.sysid, status="deceased", deceased_on=date(2025, 5, 1), expected_revision=1
        )
        assert (dead.status, dead.deceased_on, dead.revision) == ("deceased", date(2025, 5, 1), 2)
        assert [event.event_type for event in events] == ["med_patients.patient_status_changed"]
        with pytest.raises(Conflict):
            service().delete(actor=actor, patient_id=patient.sysid, expected_revision=1)
        service().delete(actor=actor, patient_id=patient.sysid, expected_revision=2)
        with pytest.raises(NotFound):
            service().get(actor=actor, patient_id=patient.sysid)
        assert service().search(actor=actor, query=CPF).items == ()
        restored = service().restore(actor=actor, patient_id=patient.sysid, expected_revision=3)
        assert (restored.sysid, restored.code, restored.cpf) == (patient.sysid, patient.code, CPF)


def test_restore_refuses_a_cpf_taken_again(ready):
    patient = new_patient(ready, cpf=CPF)
    with ready.as_user(ready.a.reception) as actor:
        service().delete(actor=actor, patient_id=patient.sysid, expected_revision=1)
    new_patient(ready, full_name="Novo dono do CPF", cpf=CPF)
    with ready.as_user(ready.a.reception) as actor, pytest.raises(Conflict):
        service().restore(actor=actor, patient_id=patient.sysid, expected_revision=2)


def test_rollback_leaves_no_patient_or_event(ready):
    from django.db import transaction

    with capture_events() as events:
        with pytest.raises(RuntimeError), transaction.atomic():
            new_patient(ready, full_name="Desfeito")
            raise RuntimeError("rollback")
    with ready.as_user(ready.a.reception) as actor:
        assert service().search(actor=actor, query="desfeito").items == ()
    assert len(events) == 1  # Captured, then rolled back with the transaction.


def test_audit_redacts_personal_data(ready):
    from skeleton.service_api.audit import AuditService

    patient = new_patient(ready, full_name="Nome Secreto", cpf=CPF, phone="11988887777", city="Cidade")
    with ready.as_user(ready.a.reception) as actor:
        service().update(actor=actor, patient_id=patient.sysid, changes=(("city", "Outra"),), expected_revision=1)
    with ready.as_user(ready.a.admin) as admin:
        entries = AuditService().history(actor=admin, table_key="med_patients.patient", record_id=patient.sysid).items
    assert [entry.operation for entry in entries][-1] in {"create", "insert", "INSERT"}
    values = {str(value) for entry in entries for change in entry.changes for value in (change.old, change.new)}
    assert not {"Nome Secreto", CPF, "11988887777", "Cidade", "Outra"} & values
    assert any("REDACTED" in value for value in values)


def test_header_and_summary_panels_follow_the_contract(ready, subtests):
    """#136: the header and the summary of a patient are read like the patient itself."""
    born = date(date.today().year - 8, 1, 1)
    own = new_patient(ready, full_name="Criança Própria", social_name="Cris", birth_date=born, sex="female")
    foreign = new_patient(ready, ready.b, full_name="Estrangeira Única")
    reception = ready.a.reception
    with subtests.test("header"), ready.as_user(reception) as actor:
        header = service().header(actor=actor, patient_id=own.sysid)
        assert (header.code, header.display_name, header.full_name, header.sex) == (
            own.code,
            "Cris",
            "Criança Própria",
            "female",
        )
        assert header.age in (7, 8) and header.needs_guardian and header.writable
        assert not header.processing_restricted and not header.anonymized and header.status == "active"
        assert not hasattr(header, "cpf") and not hasattr(header, "phone")
    with subtests.test("finance reads the header and does not write"), ready.as_user(ready.a.finance) as actor:
        assert not service().header(actor=actor, patient_id=own.sysid).writable
    for name in ("header", "summary_panels"):
        with subtests.test(f"{name}: A/B"):
            assert_denied_as_not_found(
                ready.caller(
                    lambda actor, n=name: getattr(service(), n)(actor=actor, patient_id=foreign.sysid), reception
                ),
                missing=ready.caller(
                    lambda actor, n=name: getattr(service(), n)(actor=actor, patient_id=uuid4()), reception
                ),
            )
        with subtests.test(f"{name}: app disabled"):
            assert_unavailable_when_disabled(
                ready.caller(lambda actor, n=name: getattr(service(), n)(actor=actor, patient_id=own.sysid), reception),
                disabled=lambda: ready.app_disabled("med_patients"),
            )
        with subtests.test(f"{name}: other actor"), ready.as_user(reception):
            assert_rejects_other_actor(lambda n=name: getattr(service(), n)(actor=ready.a.doctor, patient_id=own.sysid))
