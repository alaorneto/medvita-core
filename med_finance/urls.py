from django.urls import path

from . import views

app_name = "med_finance"
urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.home, name="setup"),
]
