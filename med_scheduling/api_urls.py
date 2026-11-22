from django.urls import path

from . import api

app_name = "med_scheduling_api"
urlpatterns = [
    path("schedules/", api.SchedulesAPI.as_view(), name="schedules"),
    path("schedules/<uuid:schedule_id>/slots/", api.SlotsAPI.as_view(), name="slots"),
    path("schedules/<uuid:schedule_id>/plan/", api.PlanAPI.as_view(), name="plan"),
    path("schedules/<uuid:schedule_id>/queue/", api.QueueAPI.as_view(), name="queue"),
    path("appointments/", api.AppointmentsAPI.as_view(), name="appointments"),
    path("appointments/<uuid:appointment_id>/", api.AppointmentAPI.as_view(), name="appointment"),
    # Before the transitions: "priority" is not one of them.
    path("appointments/<uuid:appointment_id>/priority/", api.AppointmentPriorityAPI.as_view(), name="priority"),
    path(
        "appointments/<uuid:appointment_id>/<slug:transition>/",
        api.AppointmentTransitionAPI.as_view(),
        name="transition",
    ),
]
