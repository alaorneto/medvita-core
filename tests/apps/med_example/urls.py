from django.http import HttpResponse
from django.urls import path

from skeleton.web.views import tenant_page


@tenant_page()
def notes(request, organization_id, patient_id=None, appointment_id=None):
    return HttpResponse("notes")


app_name = "med_example"
urlpatterns = [
    path("", notes, name="notes_home"),
    path("patients/<uuid:patient_id>/", notes, name="notes"),
    path("appointments/<uuid:appointment_id>/", notes, name="look"),
]
