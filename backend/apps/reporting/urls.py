from django.urls import path

from .views import (
    OccupancyExportView,
    OutstandingDuesExportView,
    PaymentExportView,
    ResidentExportView,
)

urlpatterns = [
    path('exports/residents/', ResidentExportView.as_view(), name='export-residents'),
    path('exports/payments/', PaymentExportView.as_view(), name='export-payments'),
    path('exports/outstanding-dues/', OutstandingDuesExportView.as_view(), name='export-outstanding-dues'),
    path('exports/occupancy/', OccupancyExportView.as_view(), name='export-occupancy'),
]
