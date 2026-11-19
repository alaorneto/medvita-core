from django.urls import path

from . import views

app_name = "med_patients"
urlpatterns = [
    path("", views.patient_list, name="list"),
    path("new/", views.patient_create, name="create"),
    path("setup/", views.registry_setup, name="setup"),
    path("setup/clinic/", views.clinic_setup, name="clinic_setup"),
    path("files/<uuid:attachment_id>/", views.attachment_download, name="attachment"),
    path("imports/", views.imports, name="imports"),
    path("imports/<uuid:batch_id>/", views.import_detail, name="import"),
    path("imports/<uuid:batch_id>/apply/", views.import_apply, name="import-apply"),
    path("imports/<uuid:batch_id>/report.csv", views.import_report, name="import-report"),
    path("<uuid:patient_id>/", views.patient_detail, name="detail"),
    path("<uuid:patient_id>/edit/", views.patient_edit, name="edit"),
    path("<uuid:patient_id>/status/", views.patient_status, name="status"),
    path("<uuid:patient_id>/guardians/", views.patient_guardians, name="guardians"),
    path("<uuid:patient_id>/guardians/<uuid:row_id>/remove/", views.guardian_remove, name="guardian-remove"),
    path("<uuid:patient_id>/coverages/", views.patient_coverages, name="coverages"),
    path("<uuid:patient_id>/coverages/<uuid:row_id>/remove/", views.coverage_remove, name="coverage-remove"),
    path("<uuid:patient_id>/consents/", views.patient_consents, name="consents"),
    path("<uuid:patient_id>/consents/<uuid:row_id>/revoke/", views.consent_revoke, name="consent-revoke"),
    path("<uuid:patient_id>/consents/<uuid:row_id>/term/", views.consent_term, name="consent-term"),
    path("<uuid:patient_id>/timeline/", views.patient_timeline, name="timeline"),
    path("<uuid:patient_id>/privacy/", views.patient_privacy, name="privacy"),
    path("<uuid:patient_id>/privacy/restrict/", views.patient_restrict, name="restrict"),
    path("<uuid:patient_id>/privacy/anonymize/", views.patient_anonymize, name="anonymize"),
]
