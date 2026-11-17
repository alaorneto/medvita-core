from django.urls import path

from . import api

app_name = "med_records_api"
urlpatterns = [
    path("charts/", api.ChartsAPI.as_view(), name="charts"),
    path("charts/<uuid:chart_id>/encounters/", api.EncountersAPI.as_view(), name="encounters"),
    path("encounters/<uuid:encounter_id>/", api.EncounterAPI.as_view(), name="encounter"),
    path("documents/<uuid:document_id>/", api.DocumentAPI.as_view(), name="document"),
]
