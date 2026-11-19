from django.urls import path

from . import api

app_name = "med_finance_api"
urlpatterns = [
    path("price-items/", api.PriceItemsAPI.as_view(), name="price_items"),
    path("charges/", api.ChargesAPI.as_view(), name="charges"),
    path("charges/<uuid:charge_id>/", api.ChargeAPI.as_view(), name="charge"),
    path("charges/<uuid:charge_id>/payments/", api.PaymentsAPI.as_view(), name="payments"),
    path("receipts/<uuid:receipt_id>/", api.ReceiptAPI.as_view(), name="receipt"),
]
