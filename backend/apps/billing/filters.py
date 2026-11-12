"""Server-side list filters for invoices and payments (UX roadmap D3).

Every filter narrows the already property-scoped queryset of the viewset, so
filtering by a property the caller can't see returns an empty list — the
same behaviour as every other list endpoint in the platform.
"""
import django_filters
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.core.periods import local_today, month_end, parse_month

from . import selectors
from .models import Discount, Invoice, Payment

# Aliases accepted by ?status= on top of the stored statuses. Both are
# derived (never stored) — see apps/billing/selectors.py.
OUTSTANDING = 'outstanding'
OVERDUE = 'overdue'


def resident_search(queryset, prefix, value):
    """Case-insensitive match on first name, last name, full name or phone."""
    value = (value or '').strip()
    if not value:
        return queryset
    query = Q()
    for term in value.split():
        query &= (
            Q(**{f'{prefix}first_name__icontains': term})
            | Q(**{f'{prefix}last_name__icontains': term})
            | Q(**{f'{prefix}phone__icontains': term})
        )
    return queryset.filter(query)


def month_range(value, param):
    first = parse_month(value, param=param)
    return first, month_end(first)


class InvoiceFilter(django_filters.FilterSet):
    resident = django_filters.UUIDFilter(field_name='resident_id')
    property = django_filters.UUIDFilter(field_name='resident__property_id')
    billing_mode = django_filters.ChoiceFilter(choices=Invoice._meta.get_field('billing_mode').choices)
    status = django_filters.CharFilter(method='filter_status')
    period = django_filters.CharFilter(method='filter_period')
    search = django_filters.CharFilter(method='filter_search')
    review = django_filters.CharFilter(method='filter_review')

    class Meta:
        model = Invoice
        fields = ['resident', 'property', 'billing_mode', 'status', 'period', 'search', 'review']

    REVIEW_FILTERS = {
        # Drafts the owner has to confirm (any review reason).
        'needs_confirmation': ~Q(review_reasons=[]),
        # Auto drafts that will be issued by the sweep.
        'scheduled': Q(review_reasons=[], auto_issue_on__isnull=False, auto_issue_held=False),
        'held': Q(review_reasons=[], auto_issue_held=True),
    }

    def filter_review(self, queryset, name, value):
        """Automatic-billing drafts: needs_confirmation / scheduled / held."""
        condition = self.REVIEW_FILTERS.get(value.strip())
        if condition is None:
            raise ValidationError(
                {'review': [_('Unknown review filter. Use needs_confirmation, scheduled or held.')]},
                code='invalid_review',
            )
        return queryset.filter(condition, status=Invoice.Status.DRAFT, auto_generated=True)

    def filter_status(self, queryset, name, value):
        """Comma-separated stored statuses, or one of the derived aliases
        `outstanding` (issued/partially-paid with a balance) and `overdue`."""
        values = [v.strip() for v in value.split(',') if v.strip()]
        if not values:
            return queryset
        if values == [OUTSTANDING]:
            return selectors.outstanding(queryset)
        if values == [OVERDUE]:
            return selectors.overdue(queryset, local_today())
        valid = set(Invoice.Status.values)
        unknown = [v for v in values if v not in valid]
        if unknown:
            raise ValidationError(
                {'status': [_('Unknown status. Use %(choices)s, or outstanding / overdue on their own.')
                            % {'choices': ', '.join(Invoice.Status.values)}]},
                code='invalid_status',
            )
        return queryset.filter(status__in=values)

    def filter_period(self, queryset, name, value):
        """Invoices whose billing period starts in the month (YYYY-MM)."""
        first, last = month_range(value, 'period')
        return queryset.filter(period_start__range=(first, last))

    def filter_search(self, queryset, name, value):
        return resident_search(queryset, 'resident__', value)


class PaymentFilter(django_filters.FilterSet):
    invoice = django_filters.UUIDFilter(field_name='invoice_id')
    # Kept for existing clients; `resident` is the documented name.
    invoice__resident = django_filters.UUIDFilter(field_name='invoice__resident_id')
    resident = django_filters.UUIDFilter(field_name='invoice__resident_id')
    property = django_filters.UUIDFilter(field_name='invoice__resident__property_id')
    payment_mode = django_filters.CharFilter(method='filter_payment_mode')
    is_advance_adjustment = django_filters.BooleanFilter()
    month = django_filters.CharFilter(method='filter_month')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Payment
        fields = [
            'invoice', 'invoice__resident', 'resident', 'property',
            'payment_mode', 'is_advance_adjustment', 'month', 'search',
        ]

    def filter_payment_mode(self, queryset, name, value):
        value = (value or '').strip()
        if not value:
            return queryset
        if value == 'advance_adjustment':
            return queryset.filter(is_advance_adjustment=True)
        if value in Payment.Mode.values:
            return queryset.filter(is_advance_adjustment=False, payment_mode=value)
        raise ValidationError(
            {'payment_mode': [_('Unknown payment mode. Use %(choices)s, or advance_adjustment.')
                              % {'choices': ', '.join(Payment.Mode.values)}]},
            code='invalid_payment_mode',
        )

    def filter_month(self, queryset, name, value):
        first, last = month_range(value, 'month')
        return queryset.filter(payment_date__range=(first, last))

    def filter_search(self, queryset, name, value):
        value = (value or '').strip()
        by_resident = resident_search(queryset, 'invoice__resident__', value)
        if not value:
            return queryset
        return queryset.filter(
            Q(pk__in=by_resident.values('pk'))
            | Q(receipt_number__icontains=value) | Q(reference__icontains=value)
        )


# `from` / `to` are Python keywords, so they can't be class attributes.
PaymentFilter.base_filters['from'] = django_filters.DateFilter(field_name='payment_date', lookup_expr='gte')
PaymentFilter.base_filters['to'] = django_filters.DateFilter(field_name='payment_date', lookup_expr='lte')


class DiscountFilter(django_filters.FilterSet):
    """?property= for the discount report (UX roadmap FE-07) — the other
    filters (resident, reason, discount_type) were already plain
    `filterset_fields` and keep working unchanged."""

    resident = django_filters.UUIDFilter(field_name='resident_id')
    property = django_filters.UUIDFilter(field_name='resident__property_id')
    reason = django_filters.ChoiceFilter(choices=Discount._meta.get_field('reason').choices)
    discount_type = django_filters.ChoiceFilter(choices=Discount._meta.get_field('discount_type').choices)

    class Meta:
        model = Discount
        fields = ['resident', 'property', 'reason', 'discount_type']
