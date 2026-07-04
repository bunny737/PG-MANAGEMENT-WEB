from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.core.roles import permissions_for
from apps.properties.services import can_view_property

from .models import Complaint, ComplaintComment


class ComplaintCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplaintComment
        fields = ['id', 'complaint', 'author', 'body', 'created_at']
        read_only_fields = ['id', 'complaint', 'author', 'created_at']


class ComplaintCommentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplaintComment
        fields = ['body']


class ComplaintSerializer(serializers.ModelSerializer):
    comments = ComplaintCommentSerializer(many=True, read_only=True)

    class Meta:
        model = Complaint
        fields = [
            'id', 'resident', 'category', 'priority', 'status', 'description', 'attachment',
            'assigned_to', 'raised_by', 'comments', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'status', 'assigned_to', 'raised_by', 'comments', 'created_at', 'updated_at']

    def validate_resident(self, value):
        request = self.context['request']
        if not can_view_property(request.user, value.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value


class ComplaintUpdateSerializer(serializers.ModelSerializer):
    """Core complaint facts are editable only while `open` — see
    ComplaintViewSet._require_open. Category/priority/description/attachment
    change; resident, status, and assignment never do through this endpoint."""

    class Meta:
        model = Complaint
        fields = ['category', 'priority', 'description', 'attachment']


class ComplaintStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = ['status']

    def validate_status(self, value):
        if value == Complaint.Status.ASSIGNED:
            raise serializers.ValidationError(
                _('Use the assign action to move a complaint to Assigned.'), code='use_assign_action',
            )
        if not self.instance.can_transition_to(value):
            raise serializers.ValidationError(
                _('Cannot move a complaint from %(current)s to %(new)s.') % {
                    'current': self.instance.get_status_display(), 'new': value,
                },
                code='invalid_status_transition',
            )
        return value


class ComplaintAssignSerializer(serializers.Serializer):
    """Open -> Assigned (PRD Module 12 workflow). `assigned_to` must be a
    staff member (manage_complaints permission) who can see the resident's
    property, in the same tenant."""

    assigned_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    def validate_assigned_to(self, value):
        complaint = self.context['complaint']
        if value.tenant_id != complaint.tenant_id:
            raise serializers.ValidationError(_('This user is not in your tenant.'), code='cross_tenant_assignee')
        if 'manage_complaints' not in permissions_for(value.role):
            raise serializers.ValidationError(
                _('This user does not have complaint-management access.'), code='assignee_not_staff'
            )
        if not can_view_property(value, complaint.resident.property_id):
            raise serializers.ValidationError(
                _('This user is not assigned to the resident\'s property.'), code='assignee_not_assigned'
            )
        return value
