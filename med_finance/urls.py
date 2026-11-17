from django.urls import path

from . import views

app_name = "med_finance"
urlpatterns = [
    path("", views.desk_view, name="desk"),
    path("", views.desk_view, name="home"),
    path("setup/", views.setup_view, name="setup"),
    path("sessions/open/", views.session_open, name="session_open"),
    path("sessions/<uuid:session_id>/", views.session_view, name="session"),
    path("sessions/<uuid:session_id>/movement/", views.session_movement, name="session_movement"),
    path("sessions/<uuid:session_id>/close/", views.session_close, name="session_close"),
    path("charges/", views.charges_view, name="charges"),
    path("charges/new/", views.charge_new, name="charge_new"),
    path("charges/<uuid:charge_id>/", views.charge_view, name="charge"),
    path("charges/<uuid:charge_id>/<slug:action>/", views.charge_action, name="charge_action"),
    path("payments/<uuid:payment_id>/reverse/", views.payment_reverse, name="payment_reverse"),
    path("appointments/<uuid:appointment_id>/collect/", views.collect, name="collect"),
    path("receipts/<uuid:receipt_id>/", views.receipt_view, name="receipt"),
    path("receipts/<uuid:receipt_id>/print/", views.receipt_print, name="receipt_print"),
    path("receipts/<uuid:receipt_id>/void/", views.receipt_void, name="receipt_void"),
    path("prices/", views.prices_view, name="prices"),
    path("patients/<uuid:patient_id>/", views.patient_section, name="patient_section"),
]
