from django.db.models import Sum
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.core.roles import permissions_for_user
from apps.properties.services import can_view_property

from . import credits, services
from .models import MAX_HOLIDAY_DAYS, MAX_RATE_PER_DAY, Announcement, FoodHoliday, FoodHolidayCredit


def _validate_property(serializer, value):
    if not can_view_property(serializer.context['request'].user, value.pk):
        raise serializers.ValidationError(_('You are not assigned to this property.'), code='property_not_assigned')
    if serializer.instance is not None and serializer.instance.property_id != value.pk:
        raise serializers.ValidationError(
            _('The property cannot be changed. Create a new one instead.'), code='property_immutable',
        )
    return value


class AnnouncementSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source='property.name', read_only=True)
    food_holiday = serializers.SerializerMethodField()
    notice_outdated = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        # `generated_from` is deliberately absent: it holds the holiday rate.
        fields = [
            'id', 'property', 'property_name', 'title', 'body', 'category', 'is_pinned', 'expires_on',
            'is_auto_text', 'food_holiday', 'notice_outdated', 'created_by', 'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_auto_text', 'created_by', 'created_at', 'updated_at']

    def get_food_holiday(self, obj) -> str | None:
        holiday = getattr(obj, 'food_holiday', None)
        return str(holiday.pk) if holiday is not None else None

    def get_notice_outdated(self, obj) -> bool:
        return services.notice_outdated(obj)

    def get_created_by_name(self, obj) -> str | None:
        user = obj.created_by
        if user is None:
            return None
        return f'{user.first_name} {user.last_name}'.strip() or str(user)

    def validate_property(self, value):
        return _validate_property(self, value)


class FoodHolidaySerializer(serializers.ModelSerializer):
    """Food holidays. Without view_finance the rate and credit figures are
    removed from the response (not nulled), like the resident money fields."""

    FINANCE_FIELDS = ('rate_per_day', 'credit_total', 'credit_count')

    property_name = serializers.CharField(source='property.name', read_only=True)
    total_days = serializers.IntegerField(read_only=True)
    is_locked = serializers.SerializerMethodField()
    notice_outdated = serializers.SerializerMethodField()
    credit_total = serializers.SerializerMethodField()
    credit_count = serializers.SerializerMethodField()
    post_notice = serializers.BooleanField(write_only=True, required=False, default=True)
    rate_per_day = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True,
        min_value=0, max_value=MAX_RATE_PER_DAY,
    )

    class Meta:
        model = FoodHoliday
        fields = [
            'id', 'property', 'property_name', 'name', 'start_date', 'end_date', 'total_days',
            'adjust_in_bill', 'rate_per_day', 'announcement', 'notice_outdated', 'is_locked',
            'credit_total', 'credit_count', 'post_notice', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'announcement', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and getattr(request.user, 'is_authenticated', False):
            if 'view_finance' not in set(permissions_for_user(request.user)):
                for name in self.FINANCE_FIELDS:
                    self.fields.pop(name, None)

    def get_is_locked(self, obj) -> bool:
        return credits.holiday_is_locked(obj)

    def get_notice_outdated(self, obj) -> bool:
        return obj.announcement is not None and services.notice_outdated(obj.announcement)

    def _live_credits(self, obj):
        return obj.credits.filter(
            status__in=(FoodHolidayCredit.Status.PENDING, FoodHolidayCredit.Status.INVOICED,
                        FoodHolidayCredit.Status.SETTLED),
        )

    def get_credit_total(self, obj) -> str:
        return str(self._live_credits(obj).aggregate(total=Sum('amount'))['total'] or '0.00')

    def get_credit_count(self, obj) -> int:
        return self._live_credits(obj).count()

    def validate_property(self, value):
        return _validate_property(self, value)

    def validate(self, attrs):
        current = self.instance

        def value(field):
            return attrs.get(field, getattr(current, field, None))

        start, end = value('start_date'), value('end_date')
        if start and end:
            if end < start:
                raise serializers.ValidationError(
                    {'end_date': _('The last day cannot be before the first day.')}, code='invalid_dates',
                )
            if (end - start).days + 1 > MAX_HOLIDAY_DAYS:
                raise serializers.ValidationError(
                    {'end_date': _('A holiday can be at most %(days)s days long.') % {'days': MAX_HOLIDAY_DAYS}},
                    code='holiday_too_long',
                )
        if value('adjust_in_bill') and value('rate_per_day') is None:
            raise serializers.ValidationError(
                {'rate_per_day': _('Enter the food charge per day to adjust in the bill.')},
                code='rate_required',
            )
        return attrs


class FoodHolidayCreditSerializer(serializers.Serializer):
    """One row of a holiday's credits table: a stored credit, or (status
    "estimated") what a resident who qualifies now would be owed."""

    id = serializers.UUIDField(allow_null=True)
    resident = serializers.UUIDField()
    resident_name = serializers.CharField()
    status = serializers.ChoiceField(choices=[*FoodHolidayCredit.Status.choices, ('estimated', _('Estimated'))])
    days = serializers.IntegerField()
    rate = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    invoice = serializers.UUIDField(allow_null=True)
    invoice_status = serializers.CharField(allow_null=True)
    clawback_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class FoodHolidayCreditTotalsSerializer(serializers.Serializer):
    """Totals of a holiday's credit rows, computed on the server so the
    client never sums money. `credited` is pending + invoiced + settled (the
    holiday's `credit_total`); estimates, waived rows and clawbacks are
    reported separately."""

    credited = serializers.DecimalField(max_digits=14, decimal_places=2)
    credited_count = serializers.IntegerField()
    estimated = serializers.DecimalField(max_digits=14, decimal_places=2)
    estimated_count = serializers.IntegerField()
    waived_count = serializers.IntegerField()
    clawback = serializers.DecimalField(max_digits=14, decimal_places=2)


class FoodHolidayCreditsSerializer(serializers.Serializer):
    credits = FoodHolidayCreditSerializer(many=True)
    totals = FoodHolidayCreditTotalsSerializer()
