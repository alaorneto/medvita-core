"""The shared clinic fixture: two organizations, the suite apps active, people and groups in each."""

import time

from skeleton.service_api.applications import ApplicationService
from skeleton.service_api.organizations import OrganizationService

from .support import APP_IDS


def test_clinic_builds_two_isolated_organizations(clinic, subtests):
    for side in (clinic.a, clinic.b):
        with subtests.test("apps and groups", organization=side.organization.slug):
            with clinic.as_user(side.admin, side.organization) as actor:
                applications = ApplicationService()
                assert all(applications.is_enabled(actor=actor, app_id=app_id) for app_id in APP_IDS.values())
                groups = {group.name: group.sysid for group in OrganizationService().groups(actor=actor).items}
                assert set(groups) == {"Recepção", "Profissionais de saúde", "Financeiro"}
                assert set(groups.values()) == set(side.groups.values())
    with subtests.test("reception of A is not a member of B"):
        with clinic.as_user(clinic.b.admin, clinic.org_b) as actor:
            members = OrganizationService().members(actor=actor).items
            assert clinic.a.reception.pk not in {member.sysid for member in members}
            assert {member.sysid for member in members} >= {clinic.b.reception.pk, clinic.b.doctor.pk}


def test_clinic_costs_little(skeleton_db):
    from .support import build_clinic

    started = time.perf_counter()
    build_clinic(slug="timed")
    elapsed = time.perf_counter() - started
    print(f"build_clinic: {elapsed:.2f}s")
    assert elapsed < 10
