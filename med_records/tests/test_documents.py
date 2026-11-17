"""Templates and simple clinical documents: drafts, issue by seal, replacement and the seal contract."""

import json

import pytest

from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.testing.sealing import assert_sealed_contract

from ..models import ClinicalDocument
from ..service_api import RecordsService, TemplateSectionInput, document_extra
from .helpers import new_patient, open_chart, prepare, start

BODY = "Paciente com quadro gripal, afastamento de 2 dias."


@pytest.fixture
def ready(clinic):
    return prepare(clinic)


@pytest.fixture
def chart(ready):
    return open_chart(ready, new_patient(ready, full_name="Maria Documento"))


def service():
    return RecordsService()


def draft(ready, chart, key="doc", **values):
    values.setdefault("kind", "med_records.certificate")
    with ready.as_user(ready.a.doctor) as doctor:
        return service().draft_document(actor=doctor, chart_id=chart.sysid, idempotency_key=key, **values)


def issue(ready, info, user=None):
    with ready.as_user(user or ready.a.doctor) as actor:
        return service().issue_document(
            actor=actor, document_id=info.header.sysid, expected_revision=info.header.revision
        )


def test_draft_fills_the_placeholders_and_issue_seals(ready, chart):
    first = draft(ready, chart)
    assert first.header.code.startswith("D") and not first.header.issued and first.writable
    assert "Maria Documento" in first.body and "{{" not in first.body
    assert draft(ready, chart).header.sysid == first.header.sysid
    with ready.as_user(ready.a.doctor) as doctor:
        changed = service().update_document(
            actor=doctor,
            document_id=first.header.sysid,
            title="Atestado médico",
            body=BODY,
            expected_revision=first.header.revision,
        )
    issued = issue(ready, changed)
    assert issued.header.issued and issued.header.author_council == "CRM-SP 123456" and not issued.writable
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(Conflict) as error:
            service().update_document(
                actor=doctor,
                document_id=issued.header.sysid,
                title="x",
                body="y",
                expected_revision=issued.header.revision,
            )
        assert error.value.code == "issued"
        assert service().verify_document(actor=doctor, document_id=issued.header.sysid).valid
        (header,) = service().documents(actor=doctor, chart_id=chart.sysid)
        assert header.title == "Atestado médico"


def test_prescription_notice_and_unknown_kind(ready, chart):
    prescription = draft(ready, chart, key="rx", kind="med_records.simple_prescription")
    assert "controle especial" in prescription.notice
    with pytest.raises(InvalidInput):
        draft(ready, chart, key="bad", kind="med_records.nope")


def test_only_the_author_and_a_professional_issue(ready, chart):
    document = draft(ready, chart)
    with pytest.raises(Forbidden):
        issue(ready, document, user=ready.a.admin)
    with ready.as_user(ready.a.admin) as admin:
        own = service().draft_document(
            actor=admin, chart_id=chart.sysid, kind="med_records.referral", idempotency_key="adm"
        )
        with pytest.raises(Conflict) as error:
            service().issue_document(actor=admin, document_id=own.header.sysid, expected_revision=own.header.revision)
        assert error.value.code == "professional_required"
    with ready.as_user(ready.a.reception) as actor, pytest.raises(NotFound):
        service().document(actor=actor, document_id=document.header.sysid)


def test_replacement_keeps_the_original(ready, chart):
    original = issue(ready, draft(ready, chart))
    pending = draft(ready, chart, key="d2")
    with ready.as_user(ready.a.doctor) as doctor:
        with pytest.raises(Conflict):
            service().replace_document(actor=doctor, document_id=pending.header.sysid, idempotency_key="r0")
        replacement = service().replace_document(actor=doctor, document_id=original.header.sysid, idempotency_key="r1")
        assert replacement.header.replaces_id == original.header.sysid and replacement.body == original.body
    newer = issue(ready, replacement)
    with ready.as_user(ready.a.doctor) as doctor:
        old = service().document(actor=doctor, document_id=original.header.sysid)
        assert old.header.replaced_by_code == newer.header.code
        assert service().verify_document(actor=doctor, document_id=original.header.sysid).valid


def test_seal_contract(ready, chart):
    keys = iter(range(100))
    doctor = ready.a.doctor  # acting() opens the doctor's context around make_record and seal.

    def make_record():
        info = service().draft_document(
            actor=doctor, chart_id=chart.sysid, kind="med_records.certificate", idempotency_key=f"c{next(keys)}"
        )
        return ClinicalDocument.objects.get(pk=info.header.sysid)

    def seal(record):
        service().issue_document(actor=doctor, document_id=record.pk, expected_revision=record.revision)
        return ClinicalDocument.objects.get(pk=record.pk)

    assert_sealed_contract(
        ClinicalDocument,
        make_record=make_record,
        seal=seal,
        acting=lambda: ready.as_user(ready.a.doctor),
        foreign=lambda: ready.as_user(ready.b.doctor, ready.org_b),
        extra=document_extra,
    )


def test_templates(ready, chart):
    with ready.as_user(ready.a.doctor) as doctor:
        shared = service().create_template(
            actor=doctor,
            name="Consulta de rotina",
            kind="encounter",
            sections=(
                TemplateSectionInput("med_records.anamnesis", data=(("chief_complaint", "Rotina"),)),
                TemplateSectionInput("med_records.plan", text="Retorno em 6 meses."),
            ),
            idempotency_key="t1",
        )
        mine = service().create_template(
            actor=doctor,
            name="Meu atestado",
            kind="document",
            document_kind="med_records.certificate",
            body="{{patient_name}} — repouso.",
            personal=True,
            idempotency_key="t2",
        )
        with pytest.raises(InvalidInput):
            service().create_template(
                actor=doctor,
                name="Ruim",
                kind="encounter",
                sections=(TemplateSectionInput("med_records.vitals", data=(("systolic", 999),)),),
                idempotency_key="t3",
            )
    encounter = start(ready, chart, key="from-template", template_id=shared.sysid)
    assert [section.section_type for section in encounter.sections] == ["med_records.anamnesis", "med_records.plan"]
    assert json.loads(encounter.sections[0].data_json) == {"chief_complaint": "Rotina"}
    document = draft(ready, chart, key="from-mine", template_id=mine.sysid)
    assert document.body == "Maria Documento — repouso."
    with ready.as_user(ready.a.admin) as admin:
        assert [item.sysid for item in service().templates(actor=admin)] == [shared.sysid]
        with pytest.raises(NotFound):
            service().update_template(actor=admin, template_id=mine.sysid, name="x", expected_revision=mine.revision)
    with ready.as_user(ready.a.doctor) as doctor:
        off = service().update_template(
            actor=doctor, template_id=shared.sysid, active=False, expected_revision=shared.revision
        )
        assert not off.is_active
        assert [item.sysid for item in service().templates(actor=doctor)] == [mine.sysid]
