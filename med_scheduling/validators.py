"""Pure validators of the scheduling app: no database."""

from __future__ import annotations

import re

STATES = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


def digits(value: object) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def valid_cpf(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{11}", value or "") or len(set(value)) == 1:
        return False
    numbers = [int(char) for char in value]
    for size in (9, 10):
        total = sum(number * (size + 1 - index) for index, number in enumerate(numbers[:size]))
        if (total * 10) % 11 % 10 != numbers[size]:
            return False
    return True


def valid_cnpj(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{14}", value or "") or len(set(value)) == 1:
        return False
    numbers = [int(char) for char in value]
    for size, weights in ((12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)), (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))):
        rest = sum(number * weight for number, weight in zip(numbers[:size], weights, strict=True)) % 11
        if (0 if rest < 2 else 11 - rest) != numbers[size]:
            return False
    return True


def valid_tax_id(value: str) -> bool:
    """CPF (a person) or CNPJ (a company); empty is accepted."""
    return not value or valid_cpf(value) or valid_cnpj(value)


def valid_state(value: str) -> bool:
    return not value or value in STATES


def valid_timezone(value: str) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True
