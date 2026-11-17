from django.urls import path

from . import api

app_name = "med_scheduling_api"
urlpatterns = [
    path("schedules/", api.SchedulesAPI.as_view(), name="schedules"),
    path("schedules/<uuid:schedule_id>/slots/", api.SlotsAPI.as_view(), name="slots"),
    path("appointments/", api.AppointmentsAPI.as_view(), name="appointments"),
    path("appointments/<uuid:appointment_id>/", api.AppointmentAPI.as_view(), name="appointment"),
    path(
        "appointments/<uuid:appointment_id>/<slug:transition>/",
        api.AppointmentTransitionAPI.as_view(),
        name="transition",
    ),
]
