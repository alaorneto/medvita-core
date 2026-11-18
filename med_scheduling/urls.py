from django.urls import path

from .views import home

app_name = "med_scheduling"
urlpatterns = [path("", home, name="home")]
