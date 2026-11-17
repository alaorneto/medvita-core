"""Fixtures shared by every test of the repository (the four apps and tests/).

``skeleton_db`` is the isolated PostgreSQL database of the core kit (``skeleton.testing.database``)
with two additions the distributed fixture does not have:

- each pytest-xdist worker uses a database of its own (``<base>_gwN_skeleton_test``), so the suite
  runs in parallel (``-n``);
- schema ``skeleton`` is migrated once per worker and then restored from a ``pg_dump`` of it before
  each test, instead of migrating for every test. Without ``pg_dump`` (or with
  ``MED_TEST_SCHEMA_TEMPLATE=0``) every test migrates, exactly as the core fixture does.

The barriers are the core's: ``disposable_database_pair()`` refuses a database that is not a
disposable ``*_skeleton_test`` one, migrations run as ``skeleton_owner`` and every assertion runs as
``skeleton_runtime``. Nothing here creates a database or a role.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

RUNTIME_ENV = "TEST_DATABASE_URL"
OWNER_ENV = "TEST_MIGRATION_DATABASE_URL"
SELECTED_ENV = "SKELETON_TEST_WORKER_DATABASE_SELECTED"
SUFFIX = "_skeleton_test"
PG_DUMP_ENV = "SKELETON_TEST_PG_DUMP"
TEMPLATE_ENV = "MED_TEST_SCHEMA_TEMPLATE"
_WORKER = re.compile(r"gw(0|[1-9][0-9]{0,2})")
_RESTRICT = re.compile(r"^\\(un)?restrict [A-Za-z0-9]+$")
_CREATE_SCHEMA = "CREATE SCHEMA skeleton;"
# A newer pg_dump than the server writes settings the server does not know; they only tune the restore.
_NEWER_CLIENT_SETTINGS = ("SET transaction_timeout = 0;",)


def _worker_url(url: str, worker: str) -> str:
    parts = urlsplit(url)
    database = parts.path[1:]
    if not database.endswith(SUFFIX) or database == SUFFIX:
        raise RuntimeError(f"The test database name must end with {SUFFIX}.")
    return parts._replace(path=f"/{database[: -len(SUFFIX)]}_{worker}{SUFFIX}").geturl()


def _select_worker_database() -> None:
    """Point this pytest-xdist worker at its own database (gw3 -> <base>_gw3_skeleton_test)."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker or os.environ.get(SELECTED_ENV) == worker:
        return
    if not _WORKER.fullmatch(worker):
        raise RuntimeError(f"Unexpected parallel worker id {worker!r}.")
    for name in (RUNTIME_ENV, OWNER_ENV):
        if os.environ.get(name):
            os.environ[name] = _worker_url(os.environ[name], worker)
    os.environ[SELECTED_ENV] = worker


_select_worker_database()


def _postgres_config(dsn: str) -> dict[str, Any]:
    import environ

    config: dict[str, Any] = environ.Env.db_url_config(dsn)
    config["OPTIONS"] = {"options": "-c search_path=skeleton,public"}
    return config


def _configure(config: dict[str, Any]) -> None:
    from django.conf import settings
    from django.db import connections
    from django.db.utils import ConnectionHandler

    connections.close_all()
    normalized = ConnectionHandler({"default": config}).settings["default"]
    settings.DATABASES["default"] = normalized
    connections.databases["default"] = normalized
    connections["default"].settings_dict = normalized


def _owner_connection(pair: Any) -> Any:
    import psycopg

    connection = psycopg.connect(pair.owner, autocommit=True)
    identity = connection.execute("SELECT current_database(), current_user").fetchone()
    role = connection.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user"
    ).fetchone()
    if identity != (pair.database, "skeleton_owner") or role is None or any(role):
        connection.close()
        raise RuntimeError("The migration connection is not the unprivileged owner of the test database.")
    return connection


def _migrate(pair: Any) -> None:
    from django.contrib.contenttypes.models import ContentType
    from django.core.management import call_command
    from django.db import connections

    from skeleton.testing.database import reset_schema

    reset_schema(pair)
    _configure(_postgres_config(pair.owner))
    call_command("migrate", verbosity=0, interactive=False)
    connections.close_all()
    ContentType.objects.clear_cache()


def _dump(pair: Any) -> str | None:
    """Plain SQL of the migrated schema skeleton, or None when pg_dump is not available."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    executable = shutil.which(os.environ.get(PG_DUMP_ENV, "pg_dump"))
    if executable is None:
        return None
    params = conninfo_to_dict(pair.owner)
    password = params.pop("password", None)
    environment = {key: value for key, value in os.environ.items() if key != "PGPASSWORD"}
    if password is not None:
        environment["PGPASSWORD"] = password
    argv = [
        executable,
        "--dbname",
        make_conninfo(**params),
        "--schema=skeleton",
        "--format=plain",
        "--column-inserts",
        "--rows-per-insert=500",
        "--no-password",
    ]
    result = subprocess.run(argv, env=environment, capture_output=True, text=True, encoding="utf-8", check=False)  # noqa: S603
    if result.returncode != 0:
        warnings.warn(f"pg_dump failed, every test migrates: {result.stderr.strip()[:200]}", stacklevel=1)
        return None
    lines = [
        line for line in result.stdout.splitlines() if not _RESTRICT.match(line) and line not in _NEWER_CLIENT_SETTINGS
    ]
    if any(line.startswith("\\") for line in lines) or lines.count(_CREATE_SCHEMA) != 1:
        warnings.warn("Unexpected pg_dump output, every test migrates.", stacklevel=1)
        return None
    lines.remove(_CREATE_SCHEMA)
    return "\n".join(lines) + "\n"


def _restore(pair: Any, template: str) -> None:
    with _owner_connection(pair) as connection, connection.transaction():
        connection.execute("SET LOCAL synchronous_commit = off")
        connection.execute("DROP SCHEMA IF EXISTS skeleton CASCADE")
        connection.execute("CREATE SCHEMA skeleton AUTHORIZATION skeleton_owner")
        connection.execute("REVOKE ALL ON SCHEMA skeleton FROM PUBLIC")
        connection.execute("GRANT USAGE ON SCHEMA skeleton TO skeleton_runtime, skeleton_audit_writer")
        # Audit functions belong to skeleton_audit_writer: the ownership transfer needs CREATE briefly.
        connection.execute("GRANT CREATE ON SCHEMA skeleton TO skeleton_audit_writer")
        connection.execute(template)
        connection.execute("REVOKE CREATE ON SCHEMA skeleton FROM skeleton_audit_writer")


def _pair() -> Any:
    from skeleton.testing.database import disposable_database_pair

    try:
        return disposable_database_pair()
    except RuntimeError as exc:
        raise pytest.UsageError(str(exc)) from exc


@pytest.fixture(scope="session")
def _schema_template(django_db_blocker: Any) -> str | None:
    if os.environ.get(TEMPLATE_ENV, "1") == "0":
        return None
    with django_db_blocker.unblock():
        pair = _pair()
        _migrate(pair)
        return _dump(pair)


@pytest.fixture
def skeleton_db(_schema_template: str | None, tmp_path: Path, django_db_blocker: Any) -> Iterator[None]:
    """Per-test database: schema skeleton as freshly migrated, assertions as skeleton_runtime."""
    from django.contrib.contenttypes.models import ContentType
    from django.db import connections
    from django.test import override_settings

    original = connections["default"].settings_dict.copy()
    with django_db_blocker.unblock():
        pair = _pair()
        if _schema_template is None:
            _migrate(pair)
        else:
            connections.close_all()
            _restore(pair, _schema_template)
            ContentType.objects.clear_cache()
        _configure(_postgres_config(pair.runtime))
        try:
            # A locmem cache per test: never share a configured cache or rate limits between tests.
            with override_settings(
                CACHES={
                    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": str(tmp_path)}
                }
            ):
                yield
        finally:
            connections.close_all()
            _configure(original)


@pytest.fixture
def clinic(skeleton_db: None) -> Any:
    """Organizations A and B with the suite apps active and admin, reception, doctor and finance in each.

    Each organization has the groups Recepção (reception), Profissionais de saúde (doctor) and
    Financeiro (finance). No container exists: each app creates its own through its setup service.
    """
    from tests.support import build_clinic

    return build_clinic()
