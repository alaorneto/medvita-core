"""Write the migration graph leaves of each app into ``migrations.leaves`` of its manifest.

    python tools/sync_leaves.py            # after makemigrations + record_infrastructure --write
    python tools/sync_leaves.py --check    # exit 1 when a manifest is behind its migrations

The core check W017 reports a manifest whose leaves differ from the graph; this script fixes it.
Needs the development environment of docs/development.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ("med_patients", "med_scheduling", "med_records", "med_finance")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    import django

    django.setup()
    from django.db.migrations.loader import MigrationLoader

    graph = MigrationLoader(None, ignore_no_migrations=True).graph
    stale = []
    for app in APPS:
        path = ROOT / app / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        leaves = sorted(name for label, name in graph.leaf_nodes() if label == manifest["app_label"])
        if manifest["migrations"]["leaves"] == leaves:
            continue
        stale.append(app)
        if not arguments.check:
            manifest["migrations"]["leaves"] = leaves
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if arguments.check and stale:
        print("stale migrations.leaves: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
