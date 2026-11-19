"""Reading the patient CSV: encodings, separators, limits, mapping and formulas (no database)."""

import pytest

from ...importer import MAX_ROWS, ImportFileError, data_rows, error_code, mapped_values, parse, safe_cell


def test_encodings_and_separators(subtests):
    cases = {
        "utf-8 with BOM and comma": "﻿nome,cpf\nJoão,52998224725\n".encode(),
        "utf-8 and semicolon": "nome;cpf\nJoão;52998224725\n".encode(),
        "windows-1252": "nome;cpf\nJoão;52998224725\n".encode("cp1252"),
    }
    for name, raw in cases.items():
        with subtests.test(name):
            parsed = parse(raw)
            assert parsed.columns == ("nome", "cpf") and parsed.total_rows == 1
            assert list(data_rows(parsed.text, parsed.delimiter)) == [(2, {"nome": "João", "cpf": "52998224725"})]


def test_refused_files(subtests):
    for name, raw, code in (
        ("empty", b"", "empty"),
        ("header only", b"nome\n", "empty"),
        ("binary", b"\x00\x01\x02nome", "not_csv"),
        ("repeated header", b"nome,nome\nA,B\n", "bad_header"),
        ("too large", b"a" * (10 * 1024 * 1024 + 1), "too_large"),
        ("too many rows", ("nome\n" + "x\n" * (MAX_ROWS + 1)).encode(), "too_many_rows"),
    ):
        with subtests.test(name), pytest.raises(ImportFileError) as error:
            parse(raw)
        assert error.value.code == code


def test_blank_rows_are_ignored_and_numbers_follow_the_file():
    parsed = parse(b"nome\nA\n\n,\nB\n")
    assert [number for number, _ in data_rows(parsed.text, parsed.delimiter)] == [2, 5]


def test_mapping_and_formulas():
    cells = {"Nome": "  =CMD()  ", "Fone": "+55 11 9999-8888", "Ignorada": "x"}
    assert mapped_values(cells, {"Nome": "full_name", "Fone": "phone"}) == {
        "full_name": "=CMD()",
        "phone": "+55 11 9999-8888",
    }
    assert [safe_cell(value) for value in ("=1+1", "+55", "-2", "@x", "ok", None)] == [
        "'=1+1",
        "'+55",
        "'-2",
        "'@x",
        "ok",
        "",
    ]
    assert error_code({"cpf": ["x"], "birth_date": ["y"]}) == "invalid_birth_date"
