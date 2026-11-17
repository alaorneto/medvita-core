from django.urls import path

from . import views

app_name = "med_patients_api"
urlpatterns = [
    path("patients/", views.PatientsAPI.as_view(), name="patients"),
    path("patients/<uuid:patient_id>/", views.PatientAPI.as_view(), name="patient"),
    path("patients/<uuid:patient_id>/guardians/", views.GuardiansAPI.as_view(), name="guardians"),
    path("patients/<uuid:patient_id>/coverages/", views.CoveragesAPI.as_view(), name="coverages"),
]
