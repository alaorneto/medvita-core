"""Pure validators and normalization of patient data (no database)."""

import pytest

from ...validators import (
    digits,
    normalize_name,
    normalize_phone,
    search_name,
    valid_cns,
    valid_cpf,
    valid_phone,
    valid_postal_code,
    valid_state,
)

VALID_CPFS = ("52998224725", "11144477735", "12345678909")
INVALID_CPFS = ("11111111111", "00000000000", "52998224724", "1234567890", "123456789012", "5299822472a", "")
# Definitive numbers (start with 1 or 2) computed by the official algorithm, and provisional ones (7, 8, 9).
VALID_CNS = (
    "123456789010000",
    "200000000000003",
    "270000000010018",
    "700000000000005",
    "800000000000001",
    "900000000000008",
)
INVALID_CNS = ("123456789010006", "200000000000002", "700000000000004", "300000000000000", "12345678901000", "")


@pytest.mark.parametrize("value", VALID_CPFS)
def test_valid_cpf(value):
    assert valid_cpf(value)


@pytest.mark.parametrize("value", INVALID_CPFS)
def test_invalid_cpf(value):
    assert not valid_cpf(value)


@pytest.mark.parametrize("value", VALID_CNS)
def test_valid_cns(value):
    assert valid_cns(value)


@pytest.mark.parametrize("value", INVALID_CNS)
def test_invalid_cns(value):
    assert not valid_cns(value)


def test_normalization(subtests):
    cases = {
        "João  da   Silva": "joao da silva",
        "ÁGUEDA Ñúñez": "agueda nunez",
        "  Ana\tMaria ": "ana maria",
        "": "",
    }
    for raw, expected in cases.items():
        with subtests.test(raw=raw):
            assert normalize_name(raw) == expected
    assert search_name("João Silva", "Joana") == "joao silva joana"
    assert search_name("João Silva") == "joao silva"
    assert digits("123.456.789-09") == "12345678909"
    assert normalize_phone("(11) 98888-7777") == "11988887777"
    assert normalize_phone("+55 11 98888-7777") == "+5511988887777"
    assert normalize_phone("") == ""


def test_formats(subtests):
    with subtests.test("phone"):
        assert valid_phone("11988887777") and valid_phone("+5511988887777") and valid_phone("")
        assert not valid_phone("123") and not valid_phone("+55119888877771234")
    with subtests.test("postal code"):
        assert valid_postal_code("01310100") and valid_postal_code("") and not valid_postal_code("0131010")
    with subtests.test("state"):
        assert valid_state("SP") and valid_state("") and not valid_state("XX") and not valid_state("sp")
