from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, ngettext

from apps.audit import log as audit_log

from .models import ContactMessage, PlatformConfig


@admin.register(PlatformConfig)
class PlatformConfigAdmin(admin.ModelAdmin):
    list_display = (
        'trial_days',
        'payment_grace_days',
        'trial_reminder_first_days_before',
        'trial_reminder_second_days_before',
        'min_billable_amount',
        'account_deletion_grace_days',
        'account_deletion_max_attempts',
        'support_email',
        'support_phone',
        'updated_at',
    )
    readonly_fields = ('updated_at',)

    def has_delete_permission(self, request, obj=None):
        return False


def _snapshot(message):
    """Audit payload: ids and status only — never the sender's personal data."""
    return {'id': str(message.pk), 'status': message.status}


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    """Inbox for the website contact form. The sender's content is read-only; the
    one thing staff change is the status, through the actions below so that every
    change (and every delete) is audit-logged against the acting user."""

    list_display = ('created_at', 'name', 'email', 'phone', 'status', 'message_preview')
    list_display_links = ('created_at', 'name')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'email', 'phone', 'message')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    actions = ('mark_handled', 'mark_new')

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description=_('Message'))
    def message_preview(self, obj):
        text = ' '.join(obj.message.split())
        return text if len(text) <= 80 else f'{text[:77]}...'

    def _set_status(self, request, queryset, status, action):
        changed = 0
        # One transaction for the whole batch: a status change and its audit row commit
        # together, and a failing audit write leaves no message changed.
        with transaction.atomic():
            for message in queryset.exclude(status=status):
                before = _snapshot(message)
                message.status = status
                message.handled_at = timezone.now() if status == ContactMessage.Status.HANDLED else None
                message.save(update_fields=['status', 'handled_at'])
                audit_log.record(
                    action=action, actor=request.user, tenant_id=None, obj=message,
                    before=before, after=_snapshot(message), request=request,
                )
                changed += 1
        self.message_user(
            request,
            ngettext('%(count)d message updated.', '%(count)d messages updated.', changed) % {'count': changed},
            messages.SUCCESS,
        )

    @admin.action(description=_('Mark selected messages as handled'))
    def mark_handled(self, request, queryset):
        self._set_status(request, queryset, ContactMessage.Status.HANDLED, 'contact_message.handled')

    @admin.action(description=_('Mark selected messages as new'))
    def mark_new(self, request, queryset):
        self._set_status(request, queryset, ContactMessage.Status.NEW, 'contact_message.reopened')

    def delete_model(self, request, obj):
        before, pk = _snapshot(obj), obj.pk
        with transaction.atomic():  # the delete and its audit row commit together
            super().delete_model(request, obj)
            obj.pk = pk  # delete() clears it; the audit row still needs the id
            audit_log.record(
                action='contact_message.deleted', actor=request.user, tenant_id=None,
                obj=obj, before=before, request=request,
            )

    def delete_queryset(self, request, queryset):
        # The bulk "delete selected" action calls this, not delete_model. It is not
        # wrapped in a transaction by Django, so the whole batch is made atomic here.
        snapshots = [(message, _snapshot(message)) for message in queryset]
        with transaction.atomic():
            super().delete_queryset(request, queryset)
            for message, before in snapshots:
                audit_log.record(
                    action='contact_message.deleted', actor=request.user, tenant_id=None,
                    obj=message, before=before, request=request,
                )
