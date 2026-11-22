"""Format of a kind of appointment: how it is paid for (no database)."""

import pytest

from skeleton.service_api import InvalidInput

from ...services import clean_type


def test_a_new_kind_is_private_unless_it_says():
    assert clean_type({"code": "consulta", "name": "Consulta"}, partial=False)["payment_kind"] == "private"
    for kind in ("private", "insurance", "courtesy"):
        clean = clean_type({"code": "c", "name": "C", "payment_kind": kind}, partial=False)
        assert clean["payment_kind"] == kind


@pytest.mark.parametrize("value", ["", "voucher", None, "Insurance"])
def test_a_payment_that_is_not_one_of_the_three_is_refused(value):
    for partial, values in ((False, {"code": "c", "name": "C"}), (True, {})):
        with pytest.raises(InvalidInput) as error:
            clean_type({**values, "payment_kind": value}, partial=partial)
        assert set(error.value.errors) == {"payment_kind"}


def test_a_change_that_does_not_name_the_payment_leaves_it_alone():
    assert "payment_kind" not in clean_type({"name": "Outro nome"}, partial=True)
    assert clean_type({"payment_kind": "courtesy"}, partial=True) == {"payment_kind": "courtesy"}
