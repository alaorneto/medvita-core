"""Pages of the records app: every read and write goes through RecordsService."""

from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from skeleton.web.views import tenant_page

from .service_api import RecordsService


@tenant_page()
def home(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    archives = RecordsService().archives(actor=request.user)
    return render(request, "med_records/home.html", {"organization_id": organization_id, "archives": archives})
