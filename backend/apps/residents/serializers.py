from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.core.roles import permissions_for_user
from apps.core.uploads import sniff_upload
from apps.properties.models import Bed
from apps.properties.services import can_view_property

from .models import (
    AbscondedRecord,
    Admission,
    Allocation,
    BlacklistEntry,
    DepositPayment,
    Resident,
    Transfer,
    Vacate,
)


class _ResidentBaseSerializer(serializers.ModelSerializer):
    """Shared Resident representation + permission-scoped financial field redaction.

    Never exposes raw file URLs or eagerly calls storage.url(): list/detail/write
    responses carry boolean presence flags (`has_aadhaar_document`, `has_pan_document`)
    while short-lived signed URLs are issued on demand from
    `GET /api/v1/residents/{id}/documents/{field}/`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
            # Finance module (view_finance) governs the billing money fields; the
            # deposit-settlement figures are also visible to Tenants->Full
            # (manage_deposits) because the move-out workflow needs them.
            user_permissions = set(permissions_for_user(request.user))
            hidden = []
            if 'view_finance' not in user_permissions:
                hidden += ['contracted_rent', 'billing_mode']
            if not user_permissions & {'view_finance', 'manage_deposits'}:
                hidden += [
                    'security_deposit_amount', 'security_deposit_agreed', 'security_deposit_pending',
                    'advance_amount', 'advance_applied_amount', 'advance_refundable',
                    'first_invoice_advance_settled',
                ]
            for field in hidden:
                self.fields.pop(field, None)

    has_aadhaar_document = serializers.SerializerMethodField()
    has_pan_document = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    block = serializers.SerializerMethodField()
    move_in_date = serializers.SerializerMethodField()
    # Read-only snapshot of the resident's admission + current allocation;
    # all null until the resident is admitted. contracted_rent comes from the
    # allocation (not the admission) so it reflects a permanent transfer.
    contracted_rent = serializers.SerializerMethodField()
    food_preference = serializers.SerializerMethodField()
    billing_mode = serializers.SerializerMethodField()
    joining_date = serializers.SerializerMethodField()
    security_deposit_amount = serializers.SerializerMethodField()
    security_deposit_agreed = serializers.SerializerMethodField()
    security_deposit_pending = serializers.SerializerMethodField()
    advance_amount = serializers.SerializerMethodField()
    advance_applied_amount = serializers.SerializerMethodField()
    advance_refundable = serializers.SerializerMethodField()
    first_invoice_advance_settled = serializers.SerializerMethodField()
    room_number = serializers.SerializerMethodField()
    bed_number = serializers.SerializerMethodField()

    _COMMON_READ_FIELDS = [
        'id', 'property', 'status',
        'first_name', 'last_name', 'gender', 'date_of_birth', 'phone', 'email',
        'permanent_address', 'current_address',
        'emergency_contact_name', 'emergency_contact_relation', 'emergency_contact_phone',
        'aadhaar_number', 'has_aadhaar_document', 'pan_number', 'has_pan_document',
        'passport_number', 'employee_id', 'student_id',
        'unit', 'block', 'move_in_date',
        'contracted_rent', 'food_preference', 'billing_mode', 'joining_date',
        'security_deposit_amount', 'security_deposit_agreed', 'security_deposit_pending',
        'advance_amount', 'advance_applied_amount', 'advance_refundable',
        'first_invoice_advance_settled',
        'room_number', 'bed_number',
        'created_at', 'updated_at',
    ]

    def get_has_aadhaar_document(self, obj) -> bool:
        return bool(obj.aadhaar_document)

    def get_has_pan_document(self, obj) -> bool:
        return bool(obj.pan_document)

    @staticmethod
    def _related(obj, name):
        # Reverse one-to-one access raises RelatedObjectDoesNotExist when absent.
        return getattr(obj, name, None)

    def _admission_value(self, obj, field, as_str=False):
        admission = self._related(obj, 'admission')
        if admission is None:
            return None
        value = getattr(admission, field)
        return str(value) if as_str else value

    def get_contracted_rent(self, obj) -> str | None:
        allocation = self._related(obj, 'allocation')
        return str(allocation.contracted_rent) if allocation else None

    def get_food_preference(self, obj) -> str | None:
        return self._admission_value(obj, 'food_preference')

    def get_billing_mode(self, obj) -> str | None:
        return self._admission_value(obj, 'billing_mode')

    def get_joining_date(self, obj) -> str | None:
        value = self._admission_value(obj, 'joining_date')
        return value.isoformat() if value else None

    def get_security_deposit_amount(self, obj) -> str | None:
        return self._admission_value(obj, 'security_deposit_amount', as_str=True)

    def get_security_deposit_agreed(self, obj) -> str | None:
        return self._admission_value(obj, 'security_deposit_agreed', as_str=True)

    def get_security_deposit_pending(self, obj) -> str | None:
        return self._admission_value(obj, 'security_deposit_pending', as_str=True)

    def get_advance_amount(self, obj) -> str | None:
        return self._admission_value(obj, 'advance_amount', as_str=True)

    def get_advance_applied_amount(self, obj) -> str | None:
        return self._admission_value(obj, 'advance_applied_amount', as_str=True)

    def get_advance_refundable(self, obj) -> str | None:
        return self._admission_value(obj, 'advance_refundable', as_str=True)

    def get_first_invoice_advance_settled(self, obj) -> bool | None:
        return self._admission_value(obj, 'first_invoice_advance_settled')

    def get_room_number(self, obj) -> str | None:
        allocation = self._related(obj, 'allocation')
        return allocation.allocated_bed.room.room_number if allocation else None

    def get_bed_number(self, obj) -> str | None:
        allocation = self._related(obj, 'allocation')
        return allocation.allocated_bed.bed_number if allocation else None

    def get_unit(self, obj) -> str:
        if hasattr(obj, 'allocation') and obj.allocation:
            return f"Room {obj.allocation.allocated_bed.room.room_number}"
        return "Not Allocated"

    def get_block(self, obj) -> str:
        if hasattr(obj, 'allocation') and obj.allocation:
            return obj.allocation.allocated_bed.room.floor.building.name
        return ""

    def get_move_in_date(self, obj) -> str:
        if hasattr(obj, 'admission') and obj.admission:
            return obj.admission.joining_date.strftime('%B %d, %Y')
        return "N/A"


class ResidentListSerializer(_ResidentBaseSerializer):
    """Explicit read serializer for GET /residents/ (no write-only file fields)."""

    class Meta:
        model = Resident
        fields = _ResidentBaseSerializer._COMMON_READ_FIELDS
        read_only_fields = fields


class ResidentSerializer(_ResidentBaseSerializer):
    aadhaar_document = serializers.FileField(write_only=True, required=False, allow_null=True)
    pan_document = serializers.FileField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Resident
        fields = [
            'id', 'property', 'status',
            'first_name', 'last_name', 'gender', 'date_of_birth', 'phone', 'email',
            'permanent_address', 'current_address',
            'emergency_contact_name', 'emergency_contact_relation', 'emergency_contact_phone',
            'aadhaar_number', 'aadhaar_document', 'has_aadhaar_document',
            'pan_number', 'pan_document', 'has_pan_document',
            'passport_number', 'employee_id', 'student_id',
            'unit', 'block', 'move_in_date',
            'contracted_rent', 'food_preference', 'billing_mode', 'joining_date',
            'security_deposit_amount', 'security_deposit_agreed', 'security_deposit_pending',
            'advance_amount', 'advance_applied_amount', 'advance_refundable',
            'first_invoice_advance_settled',
            'room_number', 'bed_number',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'updated_at']

    def validate_property(self, value):
        request = self.context['request']
        if not can_view_property(request.user, value.pk):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value

    def _validate_kyc_document(self, upload, field):
        """Aadhaar/PAN uploads sit behind a launch gate (settings.KYC_UPLOADS_ENABLED). Only a NEW
        file is gated: clearing a stored document (None) is always allowed. A file that is let through
        must really be a JPEG/PNG/PDF within the size cap."""
        if upload is None:
            return upload
        if not settings.KYC_UPLOADS_ENABLED:
            raise serializers.ValidationError(
                _('Identity document uploads are not enabled yet.'), code='kyc_uploads_disabled'
            )
        try:
            detected_type = sniff_upload(
                upload, field=field, max_bytes=settings.KYC_DOCUMENT_MAX_BYTES, code_prefix='document',
                allowed_types={'image/jpeg', 'image/png', 'application/pdf'},
            )
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(exc.detail[field])
        # Preserve the magic-byte MIME type explicitly for services.py metadata-only audit events.
        if not hasattr(self, '_detected_kyc_content_types'):
            self._detected_kyc_content_types = {}
        self._detected_kyc_content_types[field] = detected_type
        return upload

    def validate_aadhaar_document(self, value):
        return self._validate_kyc_document(value, 'aadhaar_document')

    def validate_pan_document(self, value):
        return self._validate_kyc_document(value, 'pan_document')


class ResidentStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resident
        fields = ['status']

    def validate_status(self, value):
        if not self.instance.can_transition_to(value):
            raise serializers.ValidationError(
                _('Cannot move a resident from %(current)s to %(new)s.') % {
                    'current': self.instance.get_status_display(),
                    'new': value,
                },
                code='invalid_status_transition',
            )
        return value


def bed_admits(bed, resident):
    """Can `resident` be checked in to `bed`? An available bed, or a reserved
    bed held for this resident or for nobody in particular (D9, owner
    decision 2026-10-16). Reserved -> occupied happens only here."""
    if bed.status == Bed.Status.AVAILABLE:
        return True
    return bed.status == Bed.Status.RESERVED and bed.reserved_for_id in (None, resident.pk)


class AdmissionSerializer(serializers.ModelSerializer):
    advance_refundable = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    security_deposit_pending = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Admission
        fields = [
            'id', 'resident', 'bed', 'joining_date', 'billing_mode', 'expected_stay_duration',
            'first_billing_policy', 'billing_enrolled_on', 'auto_apply_advance_to_first_invoice',
            'contracted_sharing_type', 'contracted_room_category', 'food_preference', 'contracted_rent',
            'advance_amount', 'advance_collected_date', 'advance_mode',
            # `security_deposit_amount` is the amount COLLECTED now; `_agreed` is the full deposit
            # (defaults to the collected amount when omitted, so older clients are unaffected).
            'security_deposit_amount', 'security_deposit_agreed', 'security_deposit_pending',
            'security_deposit_collected_date', 'security_deposit_mode',
            'first_month_billing_amount', 'first_month_billing_note',
            'advance_applied_amount', 'advance_refundable',
            'recorded_by', 'created_at', 'updated_at',
        ]
        # contracted_* fields are snapshotted server-side in the view
        # (invariant 2/3) — never accepted as client input.
        read_only_fields = [
            'id', 'contracted_sharing_type', 'contracted_room_category', 'contracted_rent',
            'advance_applied_amount', 'advance_refundable', 'security_deposit_pending',
            'billing_enrolled_on',
            'recorded_by', 'created_at', 'updated_at',
        ]
        extra_kwargs = {
            'advance_amount': {'min_value': Decimal('0.00')},
            # Multipart/form submissions treat an omitted checkbox as False
            # unless the serializer declares its default explicitly. Preserve
            # the model/API default for older clients that do not send this
            # newly added field.
            'auto_apply_advance_to_first_invoice': {'default': True, 'required': False},
            'security_deposit_amount': {'min_value': Decimal('0.00')},
            'security_deposit_agreed': {'min_value': Decimal('0.00'), 'required': False},
        }

    def validate(self, attrs):
        resident = attrs['resident']
        bed = attrs['bed']

        if attrs['joining_date'] > timezone.localdate():
            raise serializers.ValidationError(
                {'joining_date': _('The joining date cannot be in the future.')},
                code='future_joining_date',
            )
        if (attrs['billing_mode'] != Admission.BillingMode.MONTHLY
                and attrs.get('first_billing_policy') == Admission.FirstBillingPolicy.NEXT_BILLING_CYCLE):
            raise serializers.ValidationError(
                {'first_billing_policy': _(
                    'Automatic billing options are available only for monthly residents.'
                )},
                code='monthly_only',
            )

        if not resident.can_transition_to(Resident.Status.ACTIVE):
            raise serializers.ValidationError(
                {'resident': _(
                    'This resident is not ready for check-in — they must be Reserved first.'
                )},
                code='resident_not_ready_for_checkin',
            )
        if bed.room.floor.building.property_id != resident.property_id:
            raise serializers.ValidationError(
                {'bed': _('This bed is not in the same property as the resident.')},
                code='bed_property_mismatch',
            )
        if not bed_admits(bed, resident):
            raise serializers.ValidationError(
                {'bed': _('This bed is not available.')},
                code='bed_not_available',
            )

        request = self.context['request']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')},
                code='property_not_assigned',
            )

        # The agreed deposit defaults to what is collected now (clients that don't know about
        # partial collection send only the amount); it can never be less than what is collected.
        collected = attrs.get('security_deposit_amount', Decimal('0.00'))
        agreed = attrs.setdefault('security_deposit_agreed', collected)
        if collected > agreed:
            raise serializers.ValidationError(
                {'security_deposit_amount': _('The deposit collected cannot exceed the agreed deposit.')},
                code='deposit_exceeds_agreed',
            )

        # A collected amount needs its date and mode (the advance is recorded
        # as a payment against the first invoice, which requires both).
        for prefix in ('advance', 'security_deposit'):
            if attrs.get(f'{prefix}_amount', Decimal('0.00')) > 0:
                for suffix in ('collected_date', 'mode'):
                    if not attrs.get(f'{prefix}_{suffix}'):
                        raise serializers.ValidationError(
                            {f'{prefix}_{suffix}': _('This field is required when an amount is collected.')},
                            code='required',
                        )
        return attrs


class DepositPaymentSerializer(serializers.ModelSerializer):
    """Read shape of one security-deposit collection."""
    resident = serializers.UUIDField(source='admission.resident_id', read_only=True)

    class Meta:
        model = DepositPayment
        fields = [
            'id', 'resident', 'amount', 'payment_date', 'payment_mode', 'reference',
            'recorded_by', 'created_at',
        ]
        read_only_fields = fields


class DepositPaymentWriteSerializer(serializers.Serializer):
    """Input for recording a later deposit collection. The authoritative checks run under the
    row locks in `services.record_deposit_payment`; these are for a friendly early error."""
    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    payment_date = serializers.DateField()
    payment_mode = serializers.ChoiceField(choices=Admission.AdvanceMode.choices)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')

    def validate_resident(self, resident):
        request = self.context['request']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned',
            )
        if not hasattr(resident, 'admission'):
            raise serializers.ValidationError(
                _('This resident has not been admitted yet.'), code='resident_not_admitted',
            )
        return resident

    def validate(self, attrs):
        admission = attrs['resident'].admission
        if attrs['amount'] > admission.security_deposit_pending:
            raise serializers.ValidationError(
                {'amount': _('This exceeds the pending security deposit of %(pending)s.')
                 % {'pending': admission.security_deposit_pending}},
                code='deposit_overpaid',
            )
        return attrs


class AllocationSerializer(serializers.ModelSerializer):
    # Derived from the current bed's room (never stored — can't drift).
    actual_sharing_type = serializers.IntegerField(read_only=True)
    actual_room_category = serializers.CharField(read_only=True)

    class Meta:
        model = Allocation
        fields = [
            'id', 'resident', 'allocated_bed',
            'contracted_sharing_type', 'contracted_room_category', 'contracted_rent',
            'actual_sharing_type', 'actual_room_category',
            'is_temporary', 'temporary_since', 'expected_move_date', 'temporary_note',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class TransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transfer
        fields = [
            'id', 'resident', 'previous_bed', 'new_bed', 'is_temporary', 'reason',
            'transfer_date', 'previous_rent', 'new_rent', 'rent_effective_date',
            'recorded_by', 'created_at',
        ]
        read_only_fields = fields


class TransferCreateSerializer(serializers.Serializer):
    """Performs a transfer (PRD Module 7). `new_rent` applies only to a
    permanent transfer (`is_temporary=False`) and defaults to the new bed's
    rack rate; a temporary transfer keeps the contracted rent untouched."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    new_bed = serializers.PrimaryKeyRelatedField(queryset=Bed.objects.all())
    transfer_date = serializers.DateField()
    is_temporary = serializers.BooleanField(default=False)
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    new_rent = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None
    )
    expected_move_date = serializers.DateField(required=False, allow_null=True, default=None)
    temporary_note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        new_bed = attrs['new_bed']

        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')},
                code='property_not_assigned',
            )

        allocation = Allocation.objects.filter(resident=resident).first()
        if allocation is None:
            raise serializers.ValidationError(
                {'resident': _('This resident is not currently allocated to a bed.')},
                code='resident_not_allocated',
            )
        if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
            raise serializers.ValidationError(
                {'resident': _('Only active residents can be transferred.')},
                code='resident_not_transferable',
            )
        if new_bed.room.floor.building.property_id != resident.property_id:
            raise serializers.ValidationError(
                {'new_bed': _('This bed is not in the same property as the resident.')},
                code='bed_property_mismatch',
            )
        if new_bed.id == allocation.allocated_bed_id:
            raise serializers.ValidationError(
                {'new_bed': _('The resident is already in this bed.')},
                code='same_bed',
            )
        if new_bed.status != Bed.Status.AVAILABLE:
            raise serializers.ValidationError(
                {'new_bed': _('This bed is not available.')},
                code='bed_not_available',
            )

        attrs['allocation'] = allocation
        return attrs


class VacateSerializer(serializers.ModelSerializer):
    refund_amount = serializers.SerializerMethodField()
    is_settled = serializers.BooleanField(read_only=True)
    is_cancelled = serializers.BooleanField(read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    # Breakdown of refund_amount: deposit - deduction + unapplied advance
    # + food-holiday credit - recovered food-holiday clawback (Module 24).
    security_deposit_amount = serializers.SerializerMethodField()
    advance_amount = serializers.SerializerMethodField()
    advance_applied_amount = serializers.SerializerMethodField()
    advance_refundable = serializers.SerializerMethodField()

    class Meta:
        model = Vacate
        fields = [
            'id', 'resident', 'notice_given_date', 'expected_vacate_date', 'actual_vacate_date',
            'maintenance_deduction', 'maintenance_deduction_note',
            'refund_date', 'refund_mode', 'refund_note', 'refund_amount', 'is_settled',
            'security_deposit_amount', 'advance_amount', 'advance_applied_amount', 'advance_refundable',
            'food_holiday_credit', 'food_holiday_clawback_calculated', 'food_holiday_clawback_recovered',
            'food_holiday_clawback_unrecovered',
            'cancelled_date', 'cancellation_reason', 'cancelled_by', 'is_cancelled', 'is_open',
            'settled_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_security_deposit_amount(self, obj) -> str:
        return str(obj.resident.admission.security_deposit_amount)

    def get_advance_amount(self, obj) -> str:
        return str(obj.resident.admission.advance_amount)

    def get_advance_applied_amount(self, obj) -> str:
        return str(obj.resident.admission.advance_applied_amount)

    def get_advance_refundable(self, obj) -> str:
        return str(obj.resident.admission.advance_refundable)

    def get_refund_amount(self, obj) -> str | None:
        amount = obj.refund_amount
        return str(amount) if amount is not None else None


class VacateGiveNoticeSerializer(serializers.Serializer):
    """Step 1 of the vacating workflow (PRD Module 11): resident gives notice."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    notice_given_date = serializers.DateField()

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')}, code='property_not_assigned',
            )
        if not resident.can_transition_to(Resident.Status.NOTICE_PERIOD):
            raise serializers.ValidationError(
                {'resident': _('Only an active resident can give notice to vacate.')},
                code='resident_not_active',
            )
        # Only an *open* notice blocks a new one. A resident whose previous
        # notice was cancelled (or settled, though they'd be Vacated and caught
        # above) may give notice again — that's the whole point of allowing
        # several Vacate rows. Re-checked under a row lock in give_notice.
        if Vacate.objects.filter(
            resident=resident, cancelled_date__isnull=True, actual_vacate_date__isnull=True,
        ).exists():
            raise serializers.ValidationError(
                {'resident': _('This resident already has a vacate record.')},
                code='vacate_already_exists',
            )
        return attrs


class VacateSettlementPreviewSerializer(serializers.Serializer):
    """Shared deduction input + validation for both the settlement preview
    (this serializer, used directly) and `finalize` (which subclasses it).
    Input-only — there is no matching model field validated here beyond
    `maintenance_deduction` itself, so the two endpoints can never apply
    different deposit-cap rules to the same number."""

    maintenance_deduction = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    # Preview only (finalize redeclares it as required): the move-out date the
    # food-holiday credit/clawback is worked out for. Default: expected date.
    actual_vacate_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate_maintenance_deduction(self, value):
        if value < 0:
            raise serializers.ValidationError(_('Deduction cannot be negative.'), code='invalid_deduction')
        return value

    def validate(self, attrs):
        vacate = self.context['vacate']
        deposit = vacate.resident.admission.security_deposit_amount
        if attrs['maintenance_deduction'] > deposit:
            raise serializers.ValidationError(
                {'maintenance_deduction': _(
                    'Deduction cannot exceed the security deposit of %(deposit)s.'
                ) % {'deposit': deposit}},
                code='deduction_exceeds_deposit',
            )
        return attrs


class VacateFinalizeSerializer(VacateSettlementPreviewSerializer):
    """Step 2 of the vacating workflow (PRD Module 11): the move-out
    settlement — maintenance deduction and security deposit refund."""

    actual_vacate_date = serializers.DateField()
    maintenance_deduction_note = serializers.CharField(required=False, allow_blank=True, default='')
    refund_date = serializers.DateField(required=False, allow_null=True, default=None)
    refund_mode = serializers.ChoiceField(
        choices=Vacate.RefundMode.choices, required=False, allow_blank=True, default=''
    )
    refund_note = serializers.CharField(required=False, allow_blank=True, default='')


class VacateCancelSerializer(serializers.Serializer):
    """Withdraw a notice to vacate (Notice Period -> Active, owner request
    2026-10-07). `cancelled_date` is caller-supplied, matching every other date
    in this module (notice_given_date, actual_vacate_date, absconded_date,
    refund_date), and defaults to today. Backdating is open to any
    `manage_deposits` user — the same latitude finalize gives on
    `actual_vacate_date`. All of this is re-validated in cancel_notice()."""

    cancellation_reason = serializers.CharField(allow_blank=False)
    cancelled_date = serializers.DateField(required=False)

    def validate_cancelled_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError(
                _('Cancellation date cannot be in the future.'), code='cancelled_date_in_future',
            )
        return value

    def validate_cancellation_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                _('A reason is required to cancel notice.'), code='reason_required',
            )
        return value

    def validate(self, attrs):
        vacate = self.context['vacate']
        attrs.setdefault('cancelled_date', timezone.localdate())
        if attrs['cancelled_date'] < vacate.notice_given_date:
            raise serializers.ValidationError(
                {'cancelled_date': _('Cancellation cannot predate the notice.')},
                code='cancelled_before_notice',
            )
        return attrs


class AbscondedRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AbscondedRecord
        fields = [
            'id', 'resident', 'absconded_date', 'last_seen_date', 'absconded_note',
            'deposit_forfeited', 'deposit_applied_to_dues', 'remaining_dues',
            'food_holiday_credit', 'food_holiday_clawback',
            'dues_recovery_status', 'dues_written_off_by', 'dues_written_off_note',
            'marked_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AbscondedRecordCreateSerializer(serializers.Serializer):
    """Marks a resident absconded (PRD Module 11 'Absconded Resident
    Workflow'). Advance forfeiture and outstanding-dues calc happen
    server-side in the service, not here."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    absconded_date = serializers.DateField()
    last_seen_date = serializers.DateField(required=False, allow_null=True, default=None)
    absconded_note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')}, code='property_not_assigned',
            )
        if not resident.can_transition_to(Resident.Status.ABSCONDED):
            raise serializers.ValidationError(
                {'resident': _('Only an active resident can be marked absconded.')},
                code='resident_not_active',
            )
        return attrs


class DuesWriteOffSerializer(serializers.Serializer):
    """Write off remaining absconded dues as irrecoverable — mandatory note
    (PRD: 'owner can write off with mandatory note')."""

    note = serializers.CharField()

    def validate_note(self, value):
        if not value.strip():
            raise serializers.ValidationError(_('A note is required to write off dues.'), code='note_required')
        return value


class BlacklistEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlacklistEntry
        fields = ['id', 'resident', 'phone', 'aadhaar_number', 'reason', 'confirmed_by', 'created_at']
        read_only_fields = fields


class BlacklistConfirmSerializer(serializers.Serializer):
    """Owner/Manager confirms blacklisting (PRD: flagged automatically after
    Absconded, but blacklisting itself is never automatic)."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')}, code='property_not_assigned',
            )
        if not resident.can_transition_to(Resident.Status.BLACKLISTED):
            raise serializers.ValidationError(
                {'resident': _('This resident cannot be blacklisted from their current status.')},
                code='invalid_status_transition',
            )
        return attrs
