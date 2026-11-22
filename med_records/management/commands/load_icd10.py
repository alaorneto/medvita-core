"""Load (or refresh) the global ICD-10 table from a ``code;description`` CSV file.

The repository does not ship the table: the operator downloads the official one (DATASUS) and
converts it (docs/deployment-guide.md). The whole file is validated before anything is written,
in one transaction; running it again only updates descriptions.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from skeleton.tenancy.context import command_context

CODE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9])?$")
MAX_ROWS = 50_000


def read_rows(path: Path) -> list[tuple[str, str]]:
    """The (code, description) rows of the file, or ``CommandError`` naming the first bad line."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252")
    rows = []
    seen = set()
    for number, line in enumerate(csv.reader(text.splitlines(), delimiter=";"), start=1):
        if not line or not "".join(line).strip():
            continue
        if number == 1 and line[0].strip().lower() in {"code", "codigo", "código"}:
            continue
        if len(line) != 2:
            raise CommandError(f"Line {number}: use exactly two columns, code;description.")
        code, description = line[0].strip().upper(), line[1].strip()
        if not CODE.fullmatch(code):
            raise CommandError(f"Line {number}: invalid ICD-10 code.")
        if not description or len(description) > 300:
            raise CommandError(f"Line {number}: the description needs 1 to 300 characters.")
        if code in seen:
            raise CommandError(f"Line {number}: repeated code.")
        seen.add(code)
        rows.append((code, description))
        if len(rows) > MAX_ROWS:
            raise CommandError(f"More than {MAX_ROWS} codes.")
    return rows


class Command(BaseCommand):
    help = "Load or refresh the global ICD-10 table of the records app from a code;description CSV."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--confirm", action="store_true", help="Write the table (without it, only validate).")

    def handle(self, *args, path: Path, confirm: bool, **options):
        from ...models import Icd10Code
        from ...services import fold

        if not path.is_file():
            raise CommandError("File not found.")
        rows = read_rows(path)
        if not confirm:
            self.stdout.write(f"{len(rows)} codes are valid; nothing was written (use --confirm).")
            return
        created = updated = 0
        # The core accepts writes to a global app table only in a system context without organization.
        with command_context(reason="med_records:load_icd10"), transaction.atomic():
            existing = {row.code: row for row in Icd10Code.objects.filter(code__in=[code for code, _ in rows])}
            for code, description in rows:
                search = fold(f"{code} {description}")[:320]
                row = existing.get(code)
                if row is None:
                    Icd10Code(
                        code=code, description=description, is_category="." not in code, search_text=search
                    ).save()
                    created += 1
                elif row.description != description:
                    row.description = description
                    row.search_text = search
                    row.save(update_fields={"description", "search_text"})
                    updated += 1
        self.stdout.write(f"{created} created, {updated} updated, {len(rows) - created - updated} unchanged.")
