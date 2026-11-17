"""The core's derived access contract for the finance tables (built here, outside the app packages)."""

from itertools import count

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
