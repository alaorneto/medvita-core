"""Pages and REST API of the scheduling app: every read and write goes through SchedulingService."""

from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from rest_framework.response import Response

from skeleton.api.views import TenantAPI
from skeleton.service_api import NotFound
from skeleton.web.views import tenant_page

from .service_api import SchedulingService


@tenant_page()
def home(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    try:
        practice = SchedulingService().practice(actor=request.user)
    except NotFound:
        practice = None
    return render(request, "med_scheduling/home.html", {"organization_id": organization_id, "practice": practice})


class PracticeAPI(TenantAPI):
    def get(self, request, organization_id):
        info = SchedulingService().practice(actor=request.user)
        return Response({"sysid": str(info.sysid), "name": info.name, "timezone": info.timezone})
