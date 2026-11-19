"""The amount in words of a receipt (no database)."""

import pytest

from ...money_words import amount_words

CASES = {
    0: "zero real",
    1: "um centavo",
    100: "um real",
    101: "um real e um centavo",
    2100: "vinte e um reais",
    10000: "cem reais",
    10110: "cento e um reais e dez centavos",
    100000: "mil reais",
    123456: "mil duzentos e trinta e quatro reais e cinquenta e seis centavos",
    100000000: "um milhão de reais",
    123456789: "um milhão, duzentos e trinta e quatro mil, quinhentos e sessenta e sete reais e oitenta e nove centavos",
}


@pytest.mark.parametrize(("centavos", "words"), CASES.items())
def test_amount_words(centavos, words):
    assert amount_words(centavos) == words


def test_refuses_negative_and_float():
    for value in (-1, 1.5):
        with pytest.raises(ValueError):
            amount_words(value)
