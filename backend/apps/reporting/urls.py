from django.urls import path

from .views import (
    AnalyticsSummaryView,
    AnalyticsTrendView,
    CashFlowStatementExportView,
    ExpenseExportView,
    OccupancyExportView,
    OutstandingDuesExportView,
    PaymentExportView,
    ResidentExportView,
)

urlpatterns = [
    path('analytics/summary/', AnalyticsSummaryView.as_view(), name='analytics-summary'),
    path('analytics/trend/', AnalyticsTrendView.as_view(), name='analytics-trend'),
    path('exports/residents/', ResidentExportView.as_view(), name='export-residents'),
    path('exports/payments/', PaymentExportView.as_view(), name='export-payments'),
    path('exports/outstanding-dues/', OutstandingDuesExportView.as_view(), name='export-outstanding-dues'),
    path('exports/occupancy/', OccupancyExportView.as_view(), name='export-occupancy'),
    path('exports/expenses/', ExpenseExportView.as_view(), name='export-expenses'),
    path('exports/pnl/', CashFlowStatementExportView.as_view(), name='export-pnl'),
]
