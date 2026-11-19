"""An amount in centavos written in Portuguese words, for receipts (pure function, no database)."""

from __future__ import annotations

UNITS = (
    "zero",
    "um",
    "dois",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
)
TENS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
HUNDREDS = (
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
)
SCALES = ((10**9, "bilhão", "bilhões"), (10**6, "milhão", "milhões"), (10**3, "mil", "mil"))


def _below_thousand(number: int) -> str:
    if number == 100:
        return "cem"
    hundreds, rest = divmod(number, 100)
    parts = [HUNDREDS[hundreds]] if hundreds else []
    if rest:
        if rest < 20:
            parts.append(UNITS[rest])
        else:
            tens, units = divmod(rest, 10)
            parts.append(TENS[tens] + (f" e {UNITS[units]}" if units else ""))
    return " e ".join(parts)


def number_words(number: int) -> str:
    """A non-negative integer in words: ``1234`` → ``"mil duzentos e trinta e quatro"``."""
    if number < 0:
        raise ValueError("number_words takes a non-negative integer.")
    if number == 0:
        return UNITS[0]
    groups = []
    rest = number
    for size, singular, plural in SCALES:
        count, rest = divmod(rest, size)
        if count:
            if size == 1000 and count == 1:
                groups.append("mil")
            else:
                groups.append(f"{number_words(count)} {singular if count == 1 else plural}")
    if rest:
        groups.append(_below_thousand(rest))
    if len(groups) > 1 and rest and (rest < 100 or rest % 100 == 0):
        return ", ".join(groups[:-1]) + " e " + groups[-1]
    return ", ".join(groups) if len(groups) > 2 else " ".join(groups)


def amount_words(centavos: int) -> str:
    """``123456789`` → ``"um milhão, duzentos e trinta e quatro mil, quinhentos e sessenta e sete reais e oitenta e nove centavos"``."""
    if type(centavos) is not int or centavos < 0:
        raise ValueError("amount_words takes a non-negative integer of centavos.")
    reais, cents = divmod(centavos, 100)
    parts = []
    if reais:
        scale_only = reais % 1_000_000 == 0
        noun = "real" if reais == 1 else ("de reais" if scale_only else "reais")
        parts.append(f"{number_words(reais)} {noun}")
    if cents:
        parts.append(f"{number_words(cents)} {'centavo' if cents == 1 else 'centavos'}")
    if not parts:
        return "zero real"
    return " e ".join(parts)
