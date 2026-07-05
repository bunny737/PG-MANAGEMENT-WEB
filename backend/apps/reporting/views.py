from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.permissions import require_permission

from . import export, services


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

    permission_classes = [IsAuthenticated, require_permission('manage_payments')]

    def get(self, request):
        columns, rows = services.payment_rows(request.user, request.query_params.get('property'))
        return export.render_export(
            format=_requested_filetype(request), filename='payment-history',
            title=_('Payment History'), columns=columns, rows=rows,
        )


class OutstandingDuesExportView(APIView):
    """PRD Module 23: 'Outstanding dues' export. Gated by `manage_invoices`,
    matching the live `/invoices/outstanding/` endpoint this mirrors."""

    permission_classes = [IsAuthenticated, require_permission('manage_invoices')]

    def get(self, request):
        columns, rows = services.outstanding_dues_rows(request.user, request.query_params.get('property'))
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
