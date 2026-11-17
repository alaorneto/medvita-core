from django.shortcuts import render
from rest_framework.response import Response

from skeleton.api.views import TenantAPI
from skeleton.web.views import tenant_page

from .service_api import ArchiveService


@tenant_page()
def home(request, organization_id):
    count = ArchiveService().archive_count(actor=request.user)
    return render(
        request,
        "med_records/home.html",
        {"heading": "Prontuário", "count": count, "organization_id": organization_id},
    )


class SummaryView(TenantAPI):
    def get(self, request, organization_id):
        return Response({"count": ArchiveService().archive_count(actor=request.user)})
