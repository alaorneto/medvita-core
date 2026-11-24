"""The shared clinic of the tests: organizations A and B with the suite apps and four people each.

The core test kit has no public helper to create identities, memberships and groups outside
``build_service_scenario``. Until it has one (see AGENTS.md of the core, "skeleton/testing"), this
module uses the same core provisioning functions the kit itself uses. It lives at the root of the
repository and never ships in a package; app code and app tests use only the ``clinic`` and
``native_clients`` fixtures.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

# Load order of the suite apps: a dependency comes first. The first-party libraries (calendar,
# ledger) have no state of their own since core v0.7.0 (#792): they follow the apps that need them.
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")
APP_IDS = {
    "med_patients": "io.medvita.patients",
    "skeleton_calendar": "org.skeleton.calendar",
    "skeleton_ledger": "org.skeleton.ledger",
    "med_scheduling": "io.medvita.scheduling",
    "med_records": "io.medvita.records",
    "med_finance": "io.medvita.finance",
}
PASSWORD = "clinic-fixture-password"  # noqa: S105 - disposable identity of the test database
ROLES = ("admin", "reception", "doctor", "finance")
GROUPS = {"reception": "Recepção", "professionals": "Profissionais de saúde", "finance": "Financeiro"}
GROUP_MEMBERS = {"reception": ("reception",), "professionals": ("doctor",), "finance": ("finance",)}
NATIVE_CLIENT_ID = "medvita-desktop"
NATIVE_REDIRECT = "http://127.0.0.1/callback"
# A loopback redirect may use any port (RFC 8252): the provider matches the registered one without it.
NATIVE_CALLBACK = "http://127.0.0.1:53682/callback"


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


def portal_scenario(clinic: Clinic, app_label: str) -> Any:
    """The core's portal scenario on the clinic's organizations, admitted by ``app_label``.

    A and B get the portal on; a new person has external access to A; A's administrator is also
    external to A (``dual``); the reception of A is a member without external access; another new
    person (``outsider``) is the one the core's kit admits to B.
    """
    from skeleton.tenancy.context import system_context
    from skeleton.testing.external import ExternalScenario, enable_portal, grant_external_access

    with system_context(reason="fixture:portal-identities"):
        external = _identity(f"external-{app_label}@portal.example.test")
        outsider = _identity(f"outsider-{app_label}@portal.example.test")
    for organization in (clinic.org_a, clinic.org_b):
        enable_portal(organization)
    grant_external_access(clinic.org_a, external, app_label=app_label)
    grant_external_access(clinic.org_a, clinic.a.admin, app_label=app_label)
    return ExternalScenario(
        clinic.org_a, clinic.org_b, clinic.a.admin, external, clinic.a.admin, outsider, member=clinic.a.reception
    )


def with_new_outsider(scenario: Any, name: str) -> Any:
    """The scenario with another outsider: the core's kit admits the outsider to B on every use."""
    from dataclasses import replace

    from skeleton.tenancy.context import system_context

    with system_context(reason="fixture:portal-outsider"):
        return replace(scenario, outsider=_identity(f"outsider-{name}@portal.example.test"))


def build_clinic(slug: str = "clinic") -> Clinic:
    """Open the suite apps for every organization and build organizations A and B."""
    from skeleton.testing.applications import open_app

    for label in APPS:
        open_app(label)
    return Clinic(a=_side("a", slug), b=_side("b", slug))


# --------------------------------------------------------------------------- native clients


@functools.cache
def oidc_signing_key() -> str:
    """One RSA key per test process for the core's OIDC provider (generating it is the slow part)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@dataclass
class NativeClients:
    """Access tokens of a native client, as the Medvita Desktop gets them (#61).

    Each call runs the authorization code flow with PKCE of the core's OIDC provider for a
    signed-in browser session and returns what the desktop keeps: the access token. The provider
    needs the signing key in the settings; the ``native_clients`` fixture sets it.
    """

    registered: set[str] = field(default_factory=set)
    client_id: str = NATIVE_CLIENT_ID

    def register(self, client_id: str = NATIVE_CLIENT_ID, *, scopes: tuple[str, ...] = ()) -> None:
        """Register the client once per test; ``scopes`` are the core scopes the operator allows it."""
        from skeleton.accounts.idp.clients import register_client
        from skeleton.tenancy.context import system_context

        if client_id in self.registered:
            return
        with system_context(reason="test:native-client"):
            register_client(
                client_id=client_id,
                name="Medvita Desktop",
                redirect_uris=[NATIVE_REDIRECT],
                skip_consent=True,
                scopes=list(scopes),
            )
        self.registered.add(client_id)

    def access_token(self, user: Any, *, scope: str = "openid profile email", client_id: str = NATIVE_CLIENT_ID) -> str:
        from django.test import Client
        from django.urls import reverse

        self.register(client_id)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        browser = Client()
        browser.force_login(user)
        authorized = browser.get(
            reverse("oidc-authorize"),
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": NATIVE_CALLBACK,
                "scope": scope,
                "state": "state-1",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert authorized.status_code == 302, authorized.content
        code = parse_qs(urlsplit(authorized["Location"]).query).get("code", [None])[0]
        assert code, authorized["Location"]
        tokens = Client().post(
            reverse("oidc-token"),
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": NATIVE_CALLBACK,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert tokens.status_code == 200, tokens.content
        return tokens.json()["access_token"]

    def client(self, user: Any, **keywords: Any) -> Any:
        """A ``Client`` sending only ``Authorization: Bearer <access token>`` of ``user`` (no session, CSRF on)."""
        from django.test import Client

        token = self.access_token(user, **keywords)
        return Client(enforce_csrf_checks=True, HTTP_AUTHORIZATION=f"Bearer {token}")
