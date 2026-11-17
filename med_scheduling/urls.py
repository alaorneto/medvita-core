from django.urls import path

from . import views

app_name = "med_scheduling"
urlpatterns = [path("", views.home, name="home")]
