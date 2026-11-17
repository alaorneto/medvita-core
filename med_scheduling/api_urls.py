from django.urls import path

from . import views

app_name = "med_scheduling_api"
urlpatterns = [path("practice/", views.PracticeAPI.as_view(), name="practice")]
