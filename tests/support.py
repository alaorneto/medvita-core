"""The shared clinic of the tests: organizations A and B with the suite apps and four people each.

The core test kit has no public helper to create identities, memberships and groups outside
``build_service_scenario``. Until it has one (see AGENTS.md of the core, "skeleton/testing"), this
module uses the same core provisioning functions the kit itself uses. It lives at the root of the
repository and never ships in a package; app code and app tests use only the ``clinic`` fixture.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

# Load order of the suite apps and the first-party apps they need: a dependency comes first.
APPS = ("med_patients", "skeleton_calendar", "skeleton_ledger", "med_scheduling", "med_records", "med_finance")
APP_IDS = {
    "med_patients": "io.katua.sk.med.patients",
    "skeleton_calendar": "org.skeleton.calendar",
    "skeleton_ledger": "org.skeleton.ledger",
    "med_scheduling": "io.katua.sk.med.scheduling",
    "med_records": "io.katua.sk.med.records",
    "med_finance": "io.katua.sk.med.finance",
}
PASSWORD = "clinic-fixture-password"  # noqa: S105 - disposable identity of the test database
ROLES = ("admin", "reception", "doctor", "finance")
GROUPS = {"reception": "Recepção", "professionals": "Profissionais de saúde", "finance": "Financeiro"}
GROUP_MEMBERS = {"reception": ("reception",), "professionals": ("doctor",), "finance": ("finance",)}


@dataclass(frozen=True)
class Side:
    """One organization of the clinic: its people (by role) and its groups (by key, sysid)."""

    organization: Any
    admin: Any
    reception: Any
    doctor: Any
    finance: Any
    groups: dict[str, UUID] = field(default_factory=dict)

    @property
    def pk(self) -> UUID:
        return self.organization.pk


@dataclass(frozen=True)
class Clinic:
    a: Side
    b: Side
    password: str = PASSWORD

    @property
    def org_a(self) -> Any:
        return self.a.organization

    @property
    def org_b(self) -> Any:
        return self.b.organization

    def side(self, organization: Any) -> Side:
        return self.a if organization.pk == self.a.pk else self.b

    @contextmanager
    def app_disabled(self, app_label: str, organization: Any | None = None):
        """Disable ``app_label`` (and the apps that depend on it) in ``organization``, A by default; enable after."""
        from skeleton.testing.service_api import _set_enabled, acting_as

        side = self.side(organization or self.org_a)
        with acting_as(side.admin, side.organization, source="test:clinic-disable"):
            _set_enabled(app_label, side.admin, enabled=False)
        try:
            yield
        finally:
            with acting_as(side.admin, side.organization, source="test:clinic-enable"):
                _set_enabled(app_label, side.admin, enabled=True)

    def caller(self, function: Any, user: Any, organization: Any | None = None):
        """A zero-argument call of ``function(actor)`` in the user's own context (for the kit's asserts)."""

        def call() -> Any:
            with self.as_user(user, organization) as actor:
                return function(actor)

        return call

    @contextmanager
    def as_user(self, user: Any, organization: Any | None = None):
        """Request and tenant context of ``user`` in ``organization`` (A by default); yields the actor."""
        from skeleton.testing.service_api import acting_as

        with acting_as(user, organization or self.org_a, source="test:clinic") as actor:
            yield actor


def _identity(email: str) -> Any:
    from allauth.account.models import EmailAddress

    from skeleton.accounts.services import create_identity

    user = create_identity(email=email, password=PASSWORD)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def _side(key: str, slug: str) -> Side:
    from skeleton.access.models import Role
    from skeleton.access.services import add_group_member, create_group, provision_membership
    from skeleton.tenancy.context import system_context
    from skeleton.tenancy.models import Membership
    from skeleton.tenancy.services import create_organization
    from skeleton.testing.applications import activate_app
    from skeleton.testing.service_api import acting_as

    with system_context(reason="fixture:clinic-identities"):
        people = {role: _identity(f"{role}-{key}@{slug}.example.test") for role in ROLES}
    organization = create_organization(owner=people["admin"], slug=f"{slug}-{key}", name=f"Clínica {key.upper()}")
    with system_context(reason="fixture:clinic-members", organization_id=organization.pk):
        member = Role.objects.get(code="member")
        for role in ROLES[1:]:
            provision_membership(organization=organization, user=people[role], role=member)
    for label in APPS:
        activate_app(label, organization.pk)
    groups = {}
    with acting_as(people["admin"], organization, source="fixture:clinic-groups") as admin:
        for group_key, name in GROUPS.items():
            group = create_group(user=admin, data={"code": group_key, "name": name})
            for role in GROUP_MEMBERS[group_key]:
                membership = Membership.objects.get(user=people[role], is_active=True)
                add_group_member(user=admin, data={"group": group, "membership": membership})
            groups[group_key] = group.pk
    return Side(organization=organization, groups=groups, **people)


def build_clinic(slug: str = "clinic") -> Clinic:
    """Open the suite apps for every organization and build organizations A and B."""
    from skeleton.testing.applications import open_app

    for label in APPS:
        open_app(label)
    return Clinic(a=_side("a", slug), b=_side("b", slug))
