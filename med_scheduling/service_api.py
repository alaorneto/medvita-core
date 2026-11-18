"""API de serviços de Agenda médica: o único módulo que outras apps podem importar.

As views e a API REST desta app também chamam este serviço. Veja docs/service-api.md.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from skeleton.access.policies import authorized_queryset
from skeleton.service_api import NotFound, Page, ServiceAPI, as_utc, as_uuid, paginate, service_method

from .models import Practice

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser as User

APP_LABEL = "med_scheduling"


@dataclass(frozen=True, slots=True)
class PracticeSummary:
    """Practice como outras apps o veem; acrescente só campos de read_fields fora de sensitive_fields."""

    sysid: UUID
    code: str
    title: str
    revision: int
    updated_at: datetime


def _summary(record: Practice) -> PracticeSummary:
    return PracticeSummary(
        sysid=record.pk,
        code=record.code,
        title=record.title,
        revision=record.revision,
        updated_at=as_utc(record.updated_at),
    )


class PracticeService(ServiceAPI):
    """Consultas de Practice da organização atual."""

    app_label = APP_LABEL

    @service_method(read_only=True, since="0.1.0")
    def practice_count(self, *, actor: "User") -> int:
        """Conta os registros que o ator pode ler.

        Autorização: TablePermission read em med_scheduling.practice; conta só registros legíveis.
        Erros: Forbidden sem a permissão de tabela; Unavailable com a app desativada.
        Efeitos: nenhum.
        """
        return authorized_queryset(Practice, user=actor, action="read").count()

    @service_method(read_only=True, since="0.1.0")
    def list_practice_summaries(
        self, *, actor: "User", cursor: str | None = None, page_size: int = 25
    ) -> Page[PracticeSummary]:
        """Lista registros legíveis por ordem de criação.

        Autorização: TablePermission read em med_scheduling.practice; filtra antes de paginar.
        Erros: InvalidInput para cursor ou page_size inválidos; Forbidden; Unavailable.
        Efeitos: nenhum.
        """
        rows = authorized_queryset(Practice, user=actor, action="read").order_by("created_at", "sysid")
        return paginate(rows, convert=_summary, cursor=cursor, page_size=page_size)

    @service_method(read_only=True, since="0.1.0")
    def get_practice(self, *, actor: "User", record_id: UUID) -> PracticeSummary:
        """Devolve um registro legível pelo ator.

        Autorização: TablePermission read em med_scheduling.practice e acesso de leitura ao registro.
        Erros: NotFound se não existir, for de outra organização ou não for legível; Forbidden; Unavailable.
        Efeitos: nenhum.
        """
        record = (
            authorized_queryset(Practice, user=actor, action="read")
            .filter(pk=as_uuid(record_id, field="record_id"))
            .first()
        )
        if record is None:
            raise NotFound()
        return _summary(record)
