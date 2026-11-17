"""Pure validation and normalization of patient data: no database, no Django settings."""

from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"\s+")
_PHONE = re.compile(r"^\+?[0-9]{10,13}$")
STATES = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


def digits(value: object) -> str:
    """Only the digits of ``value`` (``"123.456.789-09"`` -> ``"12345678909"``)."""
    return "".join(char for char in str(value or "") if char.isdigit())


def normalize_name(value: object) -> str:
    """Lowercase, without accents and with single spaces: the form names are searched by."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SPACES.sub(" ", plain).strip().lower()


def search_name(full_name: str, social_name: str = "") -> str:
    """What ``Patient.search_name`` stores: the normalized full name and social name."""
    return " ".join(part for part in (normalize_name(full_name), normalize_name(social_name)) if part)[:420]


def valid_cpf(value: str) -> bool:
    """Brazilian CPF: 11 digits, not all equal, both check digits right."""
    if not re.fullmatch(r"[0-9]{11}", value or "") or len(set(value)) == 1:
        return False
    numbers = [int(char) for char in value]
    for size in (9, 10):
        total = sum(number * (size + 1 - index) for index, number in enumerate(numbers[:size]))
        if (total * 10) % 11 % 10 != numbers[size]:
            return False
    return True


def valid_cns(value: str) -> bool:
    """Cartão Nacional de Saúde: 15 digits; definitive numbers start with 1 or 2, provisional with 7, 8 or 9."""
    if not re.fullmatch(r"[0-9]{15}", value or ""):
        return False
    if value[0] in "12":
        pis = value[:11]
        total = sum(int(char) * (15 - index) for index, char in enumerate(pis))
        check = 11 - total % 11
        if check == 11:
            check = 0
        if check == 10:
            total += 2
            check = 11 - total % 11
            expected = f"{pis}001{check}"
        else:
            expected = f"{pis}000{check}"
        return expected == value
    if value[0] in "789":
        return sum(int(char) * (15 - index) for index, char in enumerate(value)) % 11 == 0
    return False


def normalize_phone(value: object) -> str:
    """Digits with an optional leading ``+`` (country code); empty stays empty."""
    text = str(value or "").strip()
    if not text:
        return ""
    plus = "+" if text.startswith("+") else ""
    return plus + digits(text)


def valid_phone(value: str) -> bool:
    return not value or bool(_PHONE.fullmatch(value))


def valid_postal_code(value: str) -> bool:
    return not value or bool(re.fullmatch(r"[0-9]{8}", value))


def valid_state(value: str) -> bool:
    return not value or value in STATES
