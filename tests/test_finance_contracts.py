"""The core's derived access contract for the finance tables (built here, outside the app packages)."""

from datetime import UTC, date, datetime
from itertools import count

import pytest

from skeleton.testing.applications import open_app
from skeleton.testing.derived import assert_derived_access_contract
from skeleton.testing.service_api import build_service_scenario

NUMBERS = count(1)
APPS = ("med_patients", "skeleton_calendar", "skeleton_ledger", "med_scheduling", "med_finance")


def _patient(organization, owner):
    from applications.med_patients.models import Patient, PatientRegistry

    registry = PatientRegistry(organization=organization, owner=owner, visibility="private", name=f"R{next(NUMBERS)}")
    registry.save()
    patient = Patient(organization=organization, registry=registry, code=f"P{next(NUMBERS):06d}", full_name="Maria")
    patient.save()
    return patient


def _book(organization, owner):
    from skeleton.contrib.ledger.models import Book

    book = Book(organization=organization, owner=owner, visibility="private", name=f"Livro {next(NUMBERS)}")
    book.save()
    return book


def test_price_item_follows_the_price_list(skeleton_db):
    from applications.med_finance.models import PriceItem, PriceList

    for label in APPS:
        open_app(label)
    scenario = build_service_scenario(PriceItem, slug="derived-priceitem")

    def make_list(*, organization, owner):
        row = PriceList(organization=organization, owner=owner, visibility="private", name=f"T{next(NUMBERS)}")
        row.save()
        return row

    def make_item(price_list):
        row = PriceItem(
            organization=price_list.organization, price_list=price_list, code="C1", description="Consulta", amount=1
        )
        row.save()
        return row

    assert_derived_access_contract(
        child_model=PriceItem, make_anchor=make_list, make_child=make_item, scenario=scenario
    )


def desk_maker():
    from applications.med_finance.models import CashDesk

    def make_desk(*, organization, owner):
        row = CashDesk(
            organization=organization,
            owner=owner,
            visibility="private",
            name=f"Caixa {next(NUMBERS)}",
            book=_book(organization, owner),
        )
        row.save()
        return row

    return make_desk


def make_session(desk):
    from applications.med_finance.models import CashSession

    row = CashSession(
        organization=desk.organization,
        desk=desk,
        opened_by=desk.owner,
        opened_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
    )
    row.save()
    return row


def make_charge(desk):
    from applications.med_finance.models import Charge

    row = Charge(
        organization=desk.organization,
        desk=desk,
        code=f"C{next(NUMBERS):08d}",
        patient=_patient(desk.organization, desk.owner),
        due_date=date(2026, 1, 1),
    )
    row.save()
    return row


CHILDREN = {}


def register_child(name):
    def decorate(function):
        CHILDREN[name] = function
        return function

    return decorate


@register_child("cashsession")
def _session(desk):
    return make_session(desk)


@register_child("cashmovement")
def _movement(desk):
    from applications.med_finance.models import CashMovement

    row = CashMovement(
        organization=desk.organization,
        session=make_session(desk),
        kind="supply",
        amount=100,
        reason="Troco",
        at=datetime(2026, 1, 1, 12, tzinfo=UTC),
    )
    row.save()
    return row


@register_child("charge")
def _charge(desk):
    return make_charge(desk)


@register_child("chargeitem")
def _item(desk):
    from applications.med_finance.models import ChargeItem

    row = ChargeItem(organization=desk.organization, charge=make_charge(desk), description="Consulta", unit_amount=1)
    row.save()
    return row


def _model(name):
    from django.apps import apps

    return apps.get_model("med_finance", name)


@pytest.mark.parametrize("table", ["cashsession", "cashmovement"])
def test_desk_tables_follow_the_desk(skeleton_db, table):
    for label in APPS:
        open_app(label)
    model = _model(table)
    scenario = build_service_scenario(model, slug=f"derived-{table}")
    assert_derived_access_contract(
        child_model=model, make_anchor=desk_maker(), make_child=CHILDREN[table], scenario=scenario
    )
