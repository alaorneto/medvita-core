"""Reading and validating a patient CSV: pure functions, no database.

The file is UTF-8 (with or without BOM) or Windows-1252, separated by ``,`` or ``;`` (decided by
the header line), at most 10 MB and 20,000 data rows. Columns are mapped to the fields of
``PatientInput``; ``full_name`` must be mapped. Every row is validated by the same rules as
``PatientService.create``. The report keeps only the row number and an error code, never a cell.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
FORMULA_PREFIXES = ("=", "+", "-", "@")


class ImportFileError(ValueError):
    """The file is not a CSV the importer accepts; ``code`` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParsedFile:
    text: str
    encoding: str
    delimiter: str
    columns: tuple[str, ...]
    total_rows: int


def decode(raw: bytes) -> tuple[str, str]:
    if len(raw) > MAX_BYTES:
        raise ImportFileError("too_large")
    if b"\x00" in raw[:4096]:
        raise ImportFileError("not_csv")
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="strict"), "cp1252"


def delimiter_of(header_line: str) -> str:
    return ";" if header_line.count(";") > header_line.count(",") else ","


def _reader(text: str, delimiter: str) -> Iterator[list[str]]:
    return csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)


def parse(raw: bytes) -> ParsedFile:
    """Decode, find the separator and the header; refuse what is not a usable CSV."""
    try:
        text, encoding = decode(raw)
    except UnicodeDecodeError:
        raise ImportFileError("not_csv") from None
    first = text.split("\n", 1)[0]
    delimiter = delimiter_of(first)
    rows = _reader(text, delimiter)
    try:
        header = next(rows)
    except StopIteration:
        raise ImportFileError("empty") from None
    except csv.Error:
        raise ImportFileError("not_csv") from None
    columns = tuple(column.strip() for column in header)
    if len(columns) < 1 or not any(columns) or len(set(columns)) != len(columns):
        raise ImportFileError("bad_header")
    total = 0
    try:
        for row in rows:
            if any(cell.strip() for cell in row):
                total += 1
                if total > MAX_ROWS:
                    raise ImportFileError("too_many_rows")
    except csv.Error:
        raise ImportFileError("not_csv") from None
    if total == 0:
        raise ImportFileError("empty")
    return ParsedFile(text=text, encoding=encoding, delimiter=delimiter, columns=columns, total_rows=total)


def data_rows(text: str, delimiter: str) -> Iterator[tuple[int, dict[str, str]]]:
    """(row number in the file, column -> cell) of each non-empty data row; the header is row 1."""
    rows = _reader(text, delimiter)
    header = [column.strip() for column in next(rows)]
    for number, row in enumerate(rows, start=2):
        if not any(cell.strip() for cell in row):
            continue
        yield number, {column: (row[index] if index < len(row) else "") for index, column in enumerate(header)}


def mapped_values(cells: dict[str, str], mapping: dict[str, str]) -> dict[str, Any]:
    """Patient fields from the mapped columns; a cell is always plain text, never a formula."""
    return {field: cells.get(column, "").strip() for column, field in mapping.items()}


def safe_cell(value: object) -> str:
    """A cell for a spreadsheet: a leading formula character is neutralized with a quote."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def error_code(errors: dict[str, Any]) -> str:
    """A stable code for a refused row: ``invalid_<first field>``."""
    return "invalid_" + sorted(errors)[0] if errors else "invalid"
