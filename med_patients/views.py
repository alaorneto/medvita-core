from django.shortcuts import render
from rest_framework.response import Response

from skeleton.api.views import TenantAPI
from skeleton.web.views import tenant_page

from .service_api import PatientService


@tenant_page()
def home(request, organization_id):
    registries = PatientService().registries(actor=request.user)
    return render(
        request,
        "med_patients/home.html",
        {"heading": "Pacientes", "count": len(registries), "organization_id": organization_id},
    )


class SummaryView(TenantAPI):
    def get(self, request, organization_id):
        return Response({"registries": len(PatientService().registries(actor=request.user))})
