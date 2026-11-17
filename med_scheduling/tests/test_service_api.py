"""Contrato e cenários da API de serviços de Agenda médica (docs/service-api.md, "Testes obrigatórios").

O teste de contrato não usa banco. Os cenários usam a fixture skeleton_db (tests/conftest.py):
PostgreSQL com o schema recriado a cada teste e asserções na role skeleton_runtime. Cada método
gerado é coberto no caminho autorizado, sem permissão de tabela, entre organizações (A/B), com a
app desativada e com ator divergente do contexto.
"""

from uuid import uuid4

import pytest

from skeleton.service_api import Forbidden
from skeleton.testing.applications import open_app
from skeleton.testing.service_api import (
    assert_denied_as_not_found,
    assert_rejects_other_actor,
    assert_service_contract,
    assert_tenant_isolated,
    assert_unavailable_when_disabled,
    build_service_scenario,
)

from ..models import Practice
from ..service_api import PracticeService

# The apps this one depends on (manifest dependencies), opened first as an operator would.
REQUIRED_APPS = ("med_patients", "skeleton_calendar")


def count(actor):
    return PracticeService().practice_count(actor=actor)


def summaries(actor):
    return PracticeService().list_practice_summaries(actor=actor).items


def detail(record_id):
    return lambda actor: PracticeService().get_practice(actor=actor, record_id=record_id)


@pytest.fixture
def scenario(skeleton_db):
    # Installed apps start unavailable (#22): the platform makes this one available, as an operator would.
    for label in (*REQUIRED_APPS, Practice._meta.app_label):
        open_app(label)
    return build_service_scenario(Practice, slug="med_scheduling-service".replace("_", "-"))


def test_service_contract():
    assert_service_contract(PracticeService)


def test_authorized_member_reads_own_organization(scenario):
    record = scenario.create(scenario.a, code="a-1", title="A one")
    assert scenario.caller(count)() == 1
    assert [item.sysid for item in scenario.caller(summaries)()] == [record.pk]
    found = scenario.caller(detail(record.pk))()
    assert (found.sysid, found.code, found.title) == (record.pk, "a-1", "A one")


def test_default_deny_without_table_permission(scenario):
    record = scenario.create(scenario.a, code="a-1", title="A one")
    for function in (count, summaries, detail(record.pk)):
        with pytest.raises(Forbidden):
            scenario.caller(function, user=scenario.denied)()


def test_private_record_of_someone_else_is_not_found(scenario):
    hidden = scenario.create(scenario.a, owner=scenario.denied, visibility="private", code="hidden", title="Hidden")
    assert_denied_as_not_found(scenario.caller(detail(hidden.pk)), missing=scenario.caller(detail(uuid4())))
    assert scenario.caller(count)() == 0
    assert hidden.pk not in {item.sysid for item in scenario.caller(summaries)()}


def test_organizations_are_isolated(scenario):
    foreign = scenario.create(scenario.b, code="foreign-code", title="Foreign title")
    scenario.create(scenario.a, code="own", title="Own title")
    markers = [foreign, "foreign-code", "Foreign title"]
    assert_tenant_isolated(scenario.caller(summaries), foreign=markers)
    assert scenario.caller(count)() == 1
    assert_denied_as_not_found(scenario.caller(detail(foreign.pk)), missing=scenario.caller(detail(uuid4())))
    # The same member reads it inside B: the isolation above is the tenant, not the grants.
    assert scenario.caller(detail(foreign.pk), organization=scenario.b)().code == "foreign-code"


def test_disabled_application_is_unavailable(scenario):
    record = scenario.create(scenario.a, code="a-1", title="A one")
    for function in (count, summaries, detail(record.pk)):
        assert_unavailable_when_disabled(scenario.caller(function), disabled=scenario.application_disabled)


def test_actor_must_match_the_context(scenario):
    record = scenario.create(scenario.a, code="a-1", title="A one")
    service = PracticeService()
    assert_rejects_other_actor(scenario.caller(lambda actor: service.practice_count(actor=scenario.denied)))
    assert_rejects_other_actor(scenario.caller(lambda actor: service.list_practice_summaries(actor=None)))
    assert_rejects_other_actor(
        scenario.caller(lambda actor: service.get_practice(actor=scenario.denied, record_id=record.pk))
    )
