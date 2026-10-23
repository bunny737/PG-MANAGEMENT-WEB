from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.periods import local_today, month_key, month_start, parse_month
from apps.core.permissions import require_any_permission, require_permission

from . import analytics, export, services
from .schema import AnalyticsSummarySerializer, AnalyticsTrendSerializer


def _requested_month(request, param='month'):
    """Optional ?month=YYYY-MM (first day of it) or None for all time."""
    return parse_month(request.query_params.get(param), param=param)


def _requested_filetype(request):
    # Deliberately NOT named "format" — DRF's DefaultContentNegotiation
    # reads ?format= itself (URL_FORMAT_OVERRIDE) to pick a *renderer*, and
    # raises Http404 during content negotiation (before the view even runs)
    # when no registered renderer matches. "filetype" avoids that collision
    # entirely — see the Module 17 spec's Decisions.
    filetype = request.query_params.get('filetype', 'csv').lower()
    if filetype not in export.FORMATS:
        raise ValidationError(
            {'filetype': _('filetype must be one of: %(formats)s.') % {'formats': ', '.join(export.FORMATS)}},
            code='invalid_filetype',
        )
    return filetype


ANALYTICS_ENTRY_PERMISSIONS = ('view_reports', 'view_dashboard')


class AnalyticsSummaryView(APIView):
    """D1 — the metric glossary (apps/reporting/analytics.py) for one month,
    ?property= (default all assigned) &month=YYYY-MM (default this month).
    Entry: view_reports or view_dashboard (the dashboard reads it too);
    finance / expenses / cash_flow groups are redacted per permission."""

    permission_classes = [IsAuthenticated, require_any_permission(*ANALYTICS_ENTRY_PERMISSIONS)]

    @extend_schema(
        parameters=[
            OpenApiParameter('property', str, description='Property UUID; default is every assigned property.'),
            OpenApiParameter('month', str, description='YYYY-MM; default is the current month.'),
        ],
        responses=AnalyticsSummarySerializer,
    )
    def get(self, request):
        params = request.query_params
        return Response(analytics.summary(request.user, params.get('property'), params.get('month')))


class AnalyticsTrendView(APIView):
    """D1b — monthly flow figures for the `months` (default 6, max 24) months
    ending at ?end=YYYY-MM (default this month), so an old month shows the
    run-up to it."""

    permission_classes = [IsAuthenticated, require_any_permission(*ANALYTICS_ENTRY_PERMISSIONS)]

    @extend_schema(
        parameters=[
            OpenApiParameter('property', str, description='Property UUID; default is every assigned property.'),
            OpenApiParameter('end', str, description='YYYY-MM; default is the current month.'),
            OpenApiParameter('months', int, description='1-24; default 6.'),
        ],
        responses=AnalyticsTrendSerializer,
    )
    def get(self, request):
        params = request.query_params
        return Response(analytics.trend(
            request.user, params.get('property'), params.get('end'), params.get('months'),
        ))


class ResidentExportView(APIView):
    """PRD Module 23: 'Resident list' export. Same visibility as
    `view_resident_profile` elsewhere (Receptionist included — this is the
    same data the resident list screen already shows them, just downloadable)."""

    permission_classes = [IsAuthenticated, require_permission('view_resident_profile')]

    def get(self, request):
        columns, rows = services.resident_rows(request.user, request.query_params.get('property'))
        return export.render_export(
            format=_requested_filetype(request), filename='residents',
            title=_('Resident List'), columns=columns, rows=rows,
        )


class PaymentExportView(APIView):
    """PRD Module 23: 'Payment history' export. Gated by `manage_payments`
    (excludes Receptionist), matching the live `/payments/` endpoint."""

    permission_classes = [IsAuthenticated, require_permission('view_finance')]

    def get(self, request):
        columns, rows = services.payment_rows(
            request.user, request.query_params.get('property'), _requested_month(request),
        )
        return export.render_export(
            format=_requested_filetype(request), filename='payment-history',
            title=_('Payment History'), columns=columns, rows=rows,
        )


class OutstandingDuesExportView(APIView):
    """PRD Module 23: 'Outstanding dues' export. Gated by `manage_invoices`,
    matching the live `/invoices/outstanding/` endpoint this mirrors."""

    permission_classes = [IsAuthenticated, require_permission('view_finance')]

    def get(self, request):
        columns, rows = services.outstanding_dues_rows(
            request.user, request.query_params.get('property'), _requested_month(request, param='period'),
        )
        return export.render_export(
            format=_requested_filetype(request), filename='outstanding-dues',
            title=_('Outstanding Dues'), columns=columns, rows=rows,
        )


class OccupancyExportView(APIView):
    """PRD Module 23: 'Occupancy report' export. Gated by `view_reports`
    (Super Admin/Owner/Manager) — a per-property bed-status snapshot."""

    permission_classes = [IsAuthenticated, require_permission('view_reports')]

    def get(self, request):
        columns, rows = services.occupancy_rows(request.user, request.query_params.get('property'))
        return export.render_export(
            format=_requested_filetype(request), filename='occupancy-report',
            title=_('Occupancy Report'), columns=columns, rows=rows,
        )


class ExpenseExportView(APIView):
    """D7: expenses for ?property=&month= (soft-deleted ones excluded)."""

    permission_classes = [IsAuthenticated, require_permission('view_expenses')]

    def get(self, request):
        columns, rows = services.expense_rows(
            request.user, request.query_params.get('property'), _requested_month(request),
        )
        return export.render_export(
            format=_requested_filetype(request), filename='expenses',
            title=_('Expenses'), columns=columns, rows=rows,
        )


class CashFlowStatementExportView(APIView):
    """D7 `/exports/pnl/`: a cash-flow statement for one month — receipts,
    refunds, expenses by category, net cash flow. Cash basis per D0, so it is
    labelled a cash-flow statement, not profit & loss. Needs both Finance and
    Expenses (a derived figure needs every constituent permission)."""

    permission_classes = [
        IsAuthenticated, require_permission('view_finance'), require_permission('view_expenses'),
    ]

    def get(self, request):
        month = _requested_month(request) or month_start(local_today())
        columns, rows = services.cash_flow_rows(request.user, request.query_params.get('property'), month)
        return export.render_export(
            format=_requested_filetype(request), filename=f'cash-flow-{month_key(month)}',
            title=_('Cash Flow Statement'), columns=columns, rows=rows,
        )
