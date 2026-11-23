from django.urls import path

from . import views

app_name = "med_scheduling"
urlpatterns = [
    path("", views.home, name="home"),
    path("day/", views.day_view, name="day"),
    path("book/", views.book_view, name="book"),
    path("reception/", views.reception_view, name="reception"),
    path("waitlist/", views.waitlist_view, name="waitlist"),
    path("waitlist/<uuid:entry_id>/cancel/", views.waitlist_cancel, name="waitlist-cancel"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/types/<uuid:type_id>/", views.type_edit_view, name="type-edit"),
    path("setup/", views.setup_view, name="setup"),
    path("schedules/", views.schedules_view, name="schedules"),
    path("calendars/<uuid:calendar_id>/subscribe/", views.calendar_subscribe, name="calendar-subscribe"),
    path("schedules/<uuid:schedule_id>/", views.schedule_view, name="schedule"),
    path("schedules/<uuid:schedule_id>/week/", views.week_view, name="week"),
    path("schedules/<uuid:schedule_id>/day/", views.day_exception_view, name="day-exception"),
    path("schedules/<uuid:schedule_id>/online/", views.schedule_online, name="schedule-online"),
    path("schedules/<uuid:schedule_id>/queue/<str:day>/", views.queue_view, name="queue"),
    path("schedules/<uuid:schedule_id>/periods/<uuid:rule_id>/", views.period_edit_view, name="period-edit"),
    path("schedules/<uuid:schedule_id>/periods/<uuid:rule_id>/remove/", views.period_remove, name="period-remove"),
    path("schedules/<uuid:schedule_id>/blocks/<uuid:block_id>/remove/", views.block_remove, name="block-remove"),
    path("appointments/<uuid:appointment_id>/", views.appointment_view, name="appointment"),
    path("appointments/<uuid:appointment_id>/reschedule/", views.appointment_reschedule, name="reschedule"),
    path("appointments/<uuid:appointment_id>/cancel/", views.appointment_cancel, name="cancel"),
    # Before the transitions: the arrival takes the priority mark, and the mark has a page of its own.
    path("appointments/<uuid:appointment_id>/check_in/", views.appointment_check_in, name="check-in"),
    path("appointments/<uuid:appointment_id>/priority/", views.appointment_priority, name="priority"),
    path("appointments/<uuid:appointment_id>/modality/", views.appointment_modality, name="modality"),
    path("appointments/<uuid:appointment_id>/<slug:name>/", views.appointment_transition, name="transition"),
    path("patients/<uuid:patient_id>/", views.patient_section, name="patient_section"),
]
