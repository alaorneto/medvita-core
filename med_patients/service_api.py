"""Service API of the patients app: the only module other apps may import (docs/service-api.md).

The pages and the REST API of this app call it too. Besides ``PatientService`` it re-exports the
registries other apps call in ``ready()`` to plug into the patient page (``extension.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.utils.translation import gettext

from skeleton.service_api import Forbidden, InvalidInput, ServiceAPI, service_method

from .models import PatientRegistry
from .policies import REGISTRY_TABLE, ids_allowed, readable_registries, writable_registries

APP_LABEL = "med_patients"
APP_ID = "io.katua.sk.med.patients"
MAX_GROUPS = 20

__all__ = ["APP_ID", "PatientService", "RegistryInfo"]


@dataclass(frozen=True, slots=True)
class RegistryInfo:
    sysid: UUID
    name: str
    is_default: bool
    revision: int
    writable: bool = False


def registry_info(registry: PatientRegistry, *, writable: bool = False) -> RegistryInfo:
    return RegistryInfo(registry.pk, registry.name, registry.is_default, registry.revision, writable)


def _key(value: object, field: str = "idempotency_key") -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise InvalidInput({field: [gettext("Use uma chave de 1 a 200 caracteres.")]})
    return value


def _group_ids(value: object, field: str) -> tuple[UUID, ...]:
    from skeleton.service_api import as_uuid

    if not isinstance(value, tuple) or len(value) > MAX_GROUPS:
        raise InvalidInput({field: [gettext("Informe até 20 grupos.")]})
    return tuple(dict.fromkeys(as_uuid(item, field=field) for item in value))


def _require_access_manager(actor: Any) -> None:
    from skeleton.service_api.access import AccessService

    if "access.manage" not in AccessService().capabilities(actor=actor):
        raise Forbidden()


class PatientService(ServiceAPI):
    """Patients of the current organization: registry, identification, contacts and consents."""

    app_label = APP_LABEL

    @service_method(read_only=False, since="0.1.0")
    def setup(
        self,
        *,
        actor: Any,
        name: str,
        writer_group_ids: tuple[UUID, ...] = (),
        reader_group_ids: tuple[UUID, ...] = (),
        idempotency_key: str,
    ) -> RegistryInfo:
        """Create the organization's default patient registry and share it with groups.

        Autorização: a capacidade ``access.manage`` (administrador da organização) e ``create`` em
        med_patients.patientregistry.
        Erros: Forbidden sem a capacidade ou a permissão de tabela; InvalidInput para nome vazio,
        chave inválida, mais de 20 grupos ou grupo de outra organização; Conflict("already_set_up")
        quando a organização já tem um cadastro padrão criado com outra chave.
        Efeitos: cria o cadastro (privado, dono o ator), dá ao papel ``member`` leitura e alteração
        da tabela do cadastro, concede leitura e alteração aos grupos de escrita e leitura aos de
        leitura; tudo na transação do chamador. A mesma chave do mesmo ator devolve o cadastro já
        criado, sem repetir concessões.
        """
        from skeleton.access.policies import has_table_permission
        from skeleton.service_api import Conflict
        from skeleton.service_api.access import AccessService
        from skeleton.tenancy.context import current_context

        from .services import deterministic_id

        key = _key(idempotency_key)
        writers = _group_ids(writer_group_ids, "writer_group_ids")
        readers = tuple(group for group in _group_ids(reader_group_ids, "reader_group_ids") if group not in writers)
        clean_name = str(name or "").strip()
        if not clean_name or len(clean_name) > 120:
            raise InvalidInput({"name": [gettext("Informe o nome do cadastro (até 120 caracteres).")]})
        _require_access_manager(actor)
        if not has_table_permission(PatientRegistry, user=actor, action="create"):
            raise Forbidden()
        sysid = deterministic_id("registry", actor, key)
        existing = PatientRegistry.objects.filter(pk=sysid).first()
        if existing is not None:
            return registry_info(existing, writable=True)
        if PatientRegistry.objects.filter(is_default=True).exists():
            raise Conflict("already_set_up")
        registry = PatientRegistry(
            sysid=sysid,
            organization_id=current_context().organization_id,
            owner_id=actor.pk,
            visibility=PatientRegistry.Visibility.PRIVATE,
            name=clean_name,
            is_default=True,
        )
        registry.save()
        access = AccessService()
        access.grant_member_table_access(actor=actor, table_key=REGISTRY_TABLE, actions=("read", "update"))
        for group in writers:
            for action in ("read", "update"):
                access.grant_record_access(
                    actor=actor, table_key=REGISTRY_TABLE, record_id=registry.pk, action=action, group_id=group
                )
        for group in readers:
            access.grant_record_access(
                actor=actor, table_key=REGISTRY_TABLE, record_id=registry.pk, action="read", group_id=group
            )
        return registry_info(registry, writable=True)

    @service_method(read_only=True, since="0.1.0")
    def registries(self, *, actor: Any) -> tuple[RegistryInfo, ...]:
        """Patient registries the actor reads, the default one first.

        Autorização: TablePermission read em med_patients.patientregistry e leitura de cada cadastro.
        Erros: Forbidden sem a permissão de tabela; Unavailable com a app desativada.
        Efeitos: nenhum.
        """
        rows = list(readable_registries(actor))
        writable = ids_allowed(writable_registries, actor)
        return tuple(registry_info(row, writable=row.pk in writable) for row in rows)
