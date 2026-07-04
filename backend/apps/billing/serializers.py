from datetime import date

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.properties.models import Property
from apps.properties.services import can_view_property
from apps.residents.models import Resident

from . import services
from .models import Discount, Invoice, InvoiceLineItem, Payment


def _windows_overlap(from1, until1, from2, until2):
    """Do two [from, until] date windows overlap? `until=None` means open-ended
    (indefinite). Boundaries are inclusive — sharing a single day counts."""
    start = max(from1, from2)
    ends = [u for u in (until1, until2) if u is not None]
    end = min(ends) if ends else None
    return end is None or start <= end


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = [
            'id', 'resident', 'discount_type', 'discount_value', 'reason',
            'note', 'valid_from', 'valid_until', 'approved_by',
            'created_at', 'updated_at',
        ]
        # approved_by is stamped from the request user server-side.
        read_only_fields = ['id', 'approved_by', 'created_at', 'updated_at']

    def validate_resident(self, value):
        request = self.context['request']
        if not can_view_property(request.user, value.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value

    def validate(self, attrs):
        instance = self.instance

        def resolved(field):
            return attrs.get(field, getattr(instance, field, None))

        discount_type = resolved('discount_type')
        discount_value = resolved('discount_value')
        valid_from = resolved('valid_from')
        valid_until = resolved('valid_until')
        resident = resolved('resident')

        if discount_value is None or discount_value <= 0:
            raise serializers.ValidationError(
                {'discount_value': _('Discount value must be greater than zero.')},
                code='invalid_discount_value',
            )
        if discount_type == Discount.DiscountType.PERCENTAGE and discount_value > 100:
            raise serializers.ValidationError(
                {'discount_value': _('A percentage discount cannot exceed 100.')},
                code='invalid_percentage',
            )
        if valid_until is not None and valid_until < valid_from:
            raise serializers.ValidationError(
                {'valid_until': _('valid_until cannot be before valid_from.')},
                code='invalid_date_range',
            )

        # At most one active discount per resident at a time — reject a window
        # overlapping any of the resident's other discounts (invariant 4: a
        # single discount line, no silent stacking).
        others = Discount.objects.filter(resident=resident)
        if instance is not None:
            others = others.exclude(pk=instance.pk)
        for other in others:
            if _windows_overlap(valid_from, valid_until, other.valid_from, other.valid_until):
                raise serializers.ValidationError(
                    {'valid_from': _('This resident already has a discount active in this period.')},
                    code='overlapping_discount',
                )
        return attrs


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = ['id', 'line_type', 'label', 'amount', 'order']
        read_only_fields = ['id']


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'resident', 'period_start', 'period_end', 'billing_mode',
            'issue_date', 'due_date', 'status', 'notes', 'created_by',
            'line_items', 'total', 'amount_paid', 'balance_due', 'is_overdue',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_total(self, obj) -> str:
        return str(obj.total)

    def get_amount_paid(self, obj) -> str:
        return str(obj.amount_paid)

    def get_balance_due(self, obj) -> str:
        return str(obj.balance_due)

    def get_is_overdue(self, obj) -> bool:
        return obj.is_overdue(date.today())


class InvoiceUpdateSerializer(serializers.ModelSerializer):
    """Only due_date / notes are editable directly (while draft); everything
    else changes through generation, line-item edits, or the issue action."""

    class Meta:
        model = Invoice
        fields = ['due_date', 'notes']


class InvoiceGenerateSerializer(serializers.Serializer):
    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    due_date = serializers.DateField()
    billing_mode = serializers.ChoiceField(
        choices=Invoice._meta.get_field('billing_mode').choices, required=False, default=None,
    )

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']

        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')},
                code='property_not_assigned',
            )
        if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
            raise serializers.ValidationError(
                {'resident': _('Only active residents can be invoiced.')},
                code='resident_not_billable',
            )
        if not Resident.objects.filter(pk=resident.pk, allocation__isnull=False).exists():
            raise serializers.ValidationError(
                {'resident': _('This resident is not allocated to a bed.')},
                code='resident_not_allocated',
            )
        if attrs['period_end'] < attrs['period_start']:
            raise serializers.ValidationError(
                {'period_end': _('period_end cannot be before period_start.')},
                code='invalid_period',
            )
        if services.resident_has_invoice_for_period(resident, attrs['period_start']):
            raise serializers.ValidationError(
                {'period_start': _('This resident already has an invoice for this period.')},
                code='duplicate_invoice',
            )
        return attrs


class InvoiceBulkGenerateSerializer(serializers.Serializer):
    property = serializers.PrimaryKeyRelatedField(queryset=Property.objects.all())
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    due_date = serializers.DateField()

    def validate(self, attrs):
        request = self.context['request']
        if not can_view_property(request.user, attrs['property'].pk):
            raise serializers.ValidationError(
                {'property': _('You are not assigned to this property.')},
                code='property_not_assigned',
            )
        if attrs['period_end'] < attrs['period_start']:
            raise serializers.ValidationError(
                {'period_end': _('period_end cannot be before period_start.')},
                code='invalid_period',
            )
        return attrs


class InvoiceLineItemWriteSerializer(serializers.ModelSerializer):
    """Add/edit an ad-hoc line on a draft invoice (electricity, penalty, ...)."""

    class Meta:
        model = InvoiceLineItem
        fields = ['id', 'line_type', 'label', 'amount', 'order']
        read_only_fields = ['id']


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id', 'invoice', 'amount', 'payment_date', 'payment_mode',
            'reference', 'recorded_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class PaymentWriteSerializer(serializers.ModelSerializer):
    """Record a manual payment against an invoice (PRD Module 10). recorded_by
    is stamped from the request user server-side."""

    class Meta:
        model = Payment
        fields = ['id', 'invoice', 'amount', 'payment_date', 'payment_mode', 'reference']
        read_only_fields = ['id']

    def validate_invoice(self, invoice):
        request = self.context['request']
        if not can_view_property(request.user, invoice.resident.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return invoice

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                _('Payment amount must be greater than zero.'), code='invalid_amount'
            )
        return value

    def validate(self, attrs):
        invoice = attrs['invoice']
        # Draft invoices are not yet a financial obligation — issue first.
        if invoice.status == Invoice.Status.DRAFT:
            raise serializers.ValidationError(
                {'invoice': _('Payments can only be recorded against an issued invoice.')},
                code='invoice_not_issued',
            )
        balance = invoice.balance_due
        if balance <= 0:
            raise serializers.ValidationError(
                {'invoice': _('This invoice is already fully paid.')},
                code='invoice_fully_paid',
            )
        # Reject overpayment: a payment never exceeds the outstanding balance, so
        # balance_due stays >= 0. Advances/deposits are Module 10's concern, not
        # an overpaid invoice.
        if attrs['amount'] > balance:
            raise serializers.ValidationError(
                {'amount': _('Payment exceeds the outstanding balance of %(balance)s.')
                 % {'balance': balance}},
                code='overpayment',
            )
        return attrs
