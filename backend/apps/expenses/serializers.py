from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.core.exceptions import Conflict
from apps.core.periods import local_today
from apps.properties.services import can_view_property

from .models import Expense, ExpenseCategory


class ExpenseCategorySerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseCategory
        fields = ['id', 'code', 'name', 'label', 'is_system', 'is_archived', 'order', 'created_at']
        read_only_fields = ['id', 'code', 'is_system', 'order', 'created_at']

    def get_label(self, obj) -> str:
        return str(obj.label)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_('A category name is required.'), code='required')
        clash = ExpenseCategory.objects.filter(is_system=False, name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                _('A category with this name already exists.'), code='duplicate_category',
            )
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.is_system:
            raise Conflict(_('Built-in categories cannot be changed.'), code='system_category')
        if self.instance is None and not attrs.get('name'):
            raise serializers.ValidationError({'name': _('A category name is required.')}, code='required')
        return attrs


class ExpenseSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source='property.name', read_only=True)
    category_name = serializers.SerializerMethodField()
    category_code = serializers.SerializerMethodField()
    has_attachment = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    # Optional on create (multipart); replace/remove later via
    # PUT/DELETE /expenses/{id}/attachment/. Never echoed back as a URL —
    # GET /expenses/{id}/attachment/ hands out a short-lived signed one.
    attachment = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = Expense
        fields = [
            'id', 'property', 'property_name', 'category', 'category_name', 'category_code',
            'amount', 'date', 'payment_mode', 'note',
            'attachment', 'has_attachment', 'attachment_content_type',
            'created_by', 'created_by_name', 'updated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'attachment_content_type', 'created_by', 'updated_by', 'created_at', 'updated_at',
        ]
        extra_kwargs = {'amount': {'min_value': 0}}

    def get_category_name(self, obj) -> str:
        return str(obj.category.label)

    def get_category_code(self, obj) -> str | None:
        return obj.category.code or None

    def get_has_attachment(self, obj) -> bool:
        return bool(obj.attachment)

    def get_created_by_name(self, obj) -> str | None:
        user = obj.created_by
        if user is None:
            return None
        return f'{user.first_name} {user.last_name}'.strip() or str(user)

    def validate_property(self, value):
        if not can_view_property(self.context['request'].user, value.pk):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned',
            )
        return value

    def validate_category(self, value):
        changing = self.instance is None or self.instance.category_id != value.pk
        if value.is_archived and changing:
            raise serializers.ValidationError(
                _('This category is archived. Pick another one.'), code='category_archived',
            )
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                _('Amount must be greater than zero.'), code='invalid_amount',
            )
        return value

    def validate_date(self, value):
        # Backdating is allowed (the app shows "Saved to Sep 2026 — View");
        # a future date is a typo — an expense is money already spent.
        if value > local_today():
            raise serializers.ValidationError(
                _('An expense date cannot be in the future.'), code='future_date',
            )
        return value
