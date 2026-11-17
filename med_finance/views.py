from django.shortcuts import render
from rest_framework.response import Response

from skeleton.api.views import TenantAPI
from skeleton.web.views import tenant_page

from .service_api import CashDeskService


@tenant_page()
def home(request, organization_id):
    count = CashDeskService().cashdesk_count(actor=request.user)
    return render(
        request,
        "med_finance/home.html",
        {"heading": "Financeiro", "count": count, "organization_id": organization_id},
    )


class SummaryView(TenantAPI):
    def get(self, request, organization_id):
        return Response({"count": CashDeskService().cashdesk_count(actor=request.user)})
