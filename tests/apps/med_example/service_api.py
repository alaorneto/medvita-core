"""Service API of the reference app (tests only): it uses the four apps only through their service APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

from skeleton.service_api import Forbidden, InvalidInput, NotFound, ServiceAPI, as_uuid, service_method

from .models import ExampleBoard, ExampleNote

APP_LABEL = "med_example"
BOARD_TABLE = "med_example.exampleboard"

__all__ = ["ExampleService", "NoteInfo"]


@dataclass(frozen=True, slots=True)
class NoteInfo:
    sysid: UUID
    patient_id: UUID
    source: str
    text: str
    keep: bool


def note_info(row: ExampleNote) -> NoteInfo:
    return NoteInfo(row.pk, row.patient_id, row.source, row.text, row.keep)


def _board(actor: Any, *, write: bool = False) -> ExampleBoard:
    from skeleton.access.policies import authorized_queryset

    rows = authorized_queryset(ExampleBoard, user=actor, action="update" if write else "read")
    board = rows.first()
    if board is None:
        if write and authorized_queryset(ExampleBoard, user=actor, action="read").exists():
            raise Forbidden()
        raise NotFound()
    return board


class ExampleService(ServiceAPI):
    """Notes about patients, written by people and by consumers of the other apps' events."""

    app_label = APP_LABEL

    @service_method(read_only=False, since="0.1.0")
    def setup(self, *, actor: Any, writer_group_ids: tuple[UUID, ...] = (), idempotency_key: str) -> UUID:
        """Create the board and share it with groups.

        Autorização: a capacidade ``access.manage`` e ``create`` na tabela do quadro.
        Erros: Forbidden; InvalidInput para chave ou grupos inválidos.
        Efeitos: cria o quadro, dá ao papel ``member`` leitura e alteração da tabela e concede
        leitura e alteração aos grupos. A mesma chave devolve o já criado.
        """
        import uuid

        from skeleton.access.policies import has_table_permission
        from skeleton.service_api.access import AccessService
        from skeleton.tenancy.context import current_context

        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise InvalidInput({"idempotency_key": [gettext("Informe a chave.")]})
        access = AccessService()
        if "access.manage" not in access.capabilities(actor=actor):
            raise Forbidden()
        if not has_table_permission(ExampleBoard, user=actor, action="create"):
            raise Forbidden()
        organization = current_context().organization_id
        sysid = uuid.uuid5(uuid.NAMESPACE_URL, f"med-example:board:{organization}:{idempotency_key}")
        if ExampleBoard.objects.filter(pk=sysid).exists():
            return sysid
        board = ExampleBoard(
            sysid=sysid, organization_id=organization, owner_id=actor.pk, visibility="private", name="Quadro"
        )
        board.save()
        access.grant_member_table_access(actor=actor, table_key=BOARD_TABLE, actions=("read", "update"))
        for group in writer_group_ids:
            for action in ("read", "update"):
                access.grant_record_access(
                    actor=actor, table_key=BOARD_TABLE, record_id=board.pk, action=action, group_id=group
                )
        return board.pk

    @service_method(read_only=True, since="0.1.0")
    def notes(self, *, actor: Any, patient_id: UUID) -> tuple[NoteInfo, ...]:
        """The notes about a patient.

        Autorização: leitura do quadro.
        Erros: NotFound sem quadro legível.
        Efeitos: nenhum.
        """
        board = _board(actor)
        rows = ExampleNote.objects.filter(board=board, patient_id=as_uuid(patient_id, field="patient_id"))
        return tuple(note_info(row) for row in rows.order_by("created_at", "sysid"))

    @service_method(read_only=False, since="0.1.0")
    def add_note(self, *, actor: Any, patient_id: UUID, text: str, keep: bool = False) -> NoteInfo:
        """Write a note about a patient the actor reads.

        Autorização: alteração no quadro e leitura do paciente.
        Erros: NotFound; Forbidden; InvalidInput para texto vazio ou longo.
        Efeitos: grava a nota.
        """
        from applications.med_patients.service_api import PatientService
        from skeleton.access.policies import require_parent_action

        if not isinstance(text, str) or not text.strip() or len(text) > 300:
            raise InvalidInput({"text": [gettext("Escreva até 300 caracteres.")]})
        board = _board(actor, write=True)
        patient = PatientService().summary(actor=actor, patient_id=as_uuid(patient_id, field="patient_id"))
        require_parent_action(ExampleNote, board, user=actor, action="create")
        row = ExampleNote(
            organization_id=board.organization_id, board=board, patient_id=patient.sysid, text=text.strip(), keep=keep
        )
        row.save()
        return note_info(row)

    @service_method(read_only=False, since="0.1.0")
    def bill(self, *, actor: Any, patient_id: UUID, amount: int, key: str, idempotency_key: str) -> UUID:
        """Bill a patient through the finance app, as a registered charge origin.

        Autorização: a de ``FinanceService.create_charge`` (alteração no caixa).
        Erros: os de ``FinanceService.create_charge``.
        Efeitos: cria (ou devolve, pela origem) a conta.
        """
        from applications.med_finance.service_api import ChargeItemInput, FinanceService

        detail = FinanceService().create_charge(
            actor=actor,
            patient_id=as_uuid(patient_id, field="patient_id"),
            items=(ChargeItemInput(description="Laudo", unit_amount=amount),),
            origin_app=APP_LABEL,
            origin_key=key,
            idempotency_key=idempotency_key,
        )
        return detail.charge.sysid
