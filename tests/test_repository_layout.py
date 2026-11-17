"""Shape of the repository: one version train, one publisher and the same core range in the four apps.

No database: reads the manifests and the package files.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")


def manifest(app):
    return json.loads((ROOT / app / "manifest.json").read_text(encoding="utf-8"))


def test_one_version_train_publisher_and_core_range():
    manifests = [manifest(app) for app in APPS]
    assert len({item["version"] for item in manifests}) == 1
    assert {item["publisher"] for item in manifests} == {"katua-tech"}
    assert len({item["compatibility"]["skeleton"] for item in manifests}) == 1
    assert [item["app_id"] for item in manifests] == [
        f"io.katua.sk.med.{name}" for name in ("patients", "scheduling", "records", "finance")
    ]


def test_dependencies_follow_the_architecture():
    version = manifest("med_patients")["version"]
    major, minor, _ = (int(part) for part in version.split("."))
    own = f">={major}.{minor}.0,<{major}.{minor + 1}.0"
    expected = {
        "med_patients": set(),
        "med_scheduling": {"io.katua.sk.med.patients", "org.skeleton.calendar"},
        "med_records": {"io.katua.sk.med.patients", "io.katua.sk.med.scheduling"},
        "med_finance": {"io.katua.sk.med.patients", "io.katua.sk.med.scheduling", "org.skeleton.ledger"},
    }
    for app in APPS:
        dependencies = manifest(app)["dependencies"]
        assert set(dependencies) == expected[app], app
        for app_id, version_range in dependencies.items():
            if app_id.startswith("io.katua.sk.med."):
                assert version_range == own, (app, app_id)


@pytest.mark.parametrize("app", APPS)
def test_each_package_carries_license_and_export_rules(app):
    package = ROOT / app
    assert (package / "LICENSE").read_text(encoding="utf-8") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    rules = (package / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert ".gitattributes export-ignore" in rules
    assert "AGENTS.md export-ignore" in rules
