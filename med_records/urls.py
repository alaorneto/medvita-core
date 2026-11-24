from django.urls import path

from . import views

app_name = "med_records"
urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup_view, name="setup"),
    path("templates/", views.templates_view, name="templates"),
    path("templates/<uuid:template_id>/deactivate/", views.template_deactivate, name="template_deactivate"),
    path("patients/<uuid:patient_id>/", views.patient_section, name="patient_section"),
    path("patients/<uuid:patient_id>/open/", views.chart_open, name="chart_open"),
    path("charts/<uuid:chart_id>/encounters/new/", views.encounter_new, name="encounter_new"),
    path("charts/<uuid:chart_id>/documents/new/", views.document_new, name="document_new"),
    path("charts/<uuid:chart_id>/lists/", views.lists_view, name="lists"),
    path("charts/<uuid:chart_id>/lists/<slug:kind>/<uuid:item_id>/end/", views.list_end, name="list_end"),
    path("charts/<uuid:chart_id>/attach/", views.chart_attach, name="chart_attach"),
    path("charts/<uuid:chart_id>/trail/", views.access_log_view, name="access_log"),
    path("attachments/<uuid:attachment_id>/", views.attachment_download, name="attachment"),
    path("appointments/<uuid:appointment_id>/attend/", views.attend, name="attend"),
    path("encounters/<uuid:encounter_id>/", views.encounter_view, name="encounter"),
    path("encounters/<uuid:encounter_id>/edit/", views.encounter_edit, name="encounter_edit"),
    path("encounters/<uuid:encounter_id>/sign/", views.encounter_sign, name="encounter_sign"),
    path("encounters/<uuid:encounter_id>/discard/", views.encounter_discard, name="encounter_discard"),
    path(
        "encounters/<uuid:encounter_id>/sections/<uuid:section_id>/remove/",
        views.section_remove,
        name="section_remove",
    ),
    path("encounters/<uuid:encounter_id>/print/", views.encounter_print, name="encounter_print"),
    path("encounters/<uuid:encounter_id>/addendum/", views.addendum, name="addendum"),
    path("documents/<uuid:document_id>/", views.document_view, name="document"),
    path("documents/<uuid:document_id>/edit/", views.document_edit, name="document_edit"),
    path("documents/<uuid:document_id>/print/", views.document_print, name="document_print"),
    path("documents/<uuid:document_id>/issue/", views.document_issue, name="document_issue"),
    path("documents/<uuid:document_id>/replace/", views.document_replace, name="document_replace"),
]
