"""Pages of the finance app: every read and write goes through FinanceService."""

from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from skeleton.web.views import tenant_page

from .service_api import FinanceService


@tenant_page()
def home(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    desks = FinanceService().desks(actor=request.user)
    return render(request, "med_finance/home.html", {"organization_id": organization_id, "desks": desks})
