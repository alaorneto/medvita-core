"""Each app's docs/service-api.md carries the reference generated from its service_api.py (no drift).

No database: imports the service modules and compares the generated block with the file.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("service_reference", ROOT / "tools" / "service_reference.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


@pytest.mark.parametrize("app", reference.APPS)
def test_service_reference_is_up_to_date(app):
    path = ROOT / app / "docs" / "service-api.md"
    text = path.read_text(encoding="utf-8")
    if reference.BEGIN not in text:
        pytest.skip(f"{app} does not generate its reference yet")
    assert reference.rewrite(app, check=True), f"run: python tools/service_reference.py {app}"
