"""Registry of known notification types (PRD Module 18 + V2 channels).

Adding a new notification TYPE (a new business event to notify on) is still
a code change — it needs a new trigger point somewhere that calls
`services.notify(...)`. What no longer requires a code change is the
notification's WORDING (a `NotificationTemplate` row, editable via Django
admin) or its recurring SCHEDULE (a django-celery-beat `PeriodicTask`, see
`apps.notifications.tasks.run_due_sweep`).

`channels` — which channels this type is sent on by default. A channel only
actually fires if both a handler is registered (`apps.notifications.channels`)
and an active `NotificationTemplate` exists for it.
`optional` — False means the recipient cannot opt out via
`NotificationPreference` (e.g. a payment receipt is not optional).
`context_vars` — documents the template placeholders available for this
type; shown as help_text on the `NotificationTemplate` admin form.
"""

NOTIFICATION_TYPES = {
    'welcome': {
        'label': 'Welcome',
        'channels': ['email'],
        'optional': False,
        'context_vars': ['name', 'business_name'],
    },
    'trial_expiry_reminder': {
        'label': 'Trial Expiry Reminder',
        'channels': ['email', 'push'],
        'optional': False,
        'context_vars': ['name', 'business', 'days', 'end_date'],
    },
    'invoice_issued': {
        'label': 'Invoice Issued',
        'channels': ['email', 'push'],
        'optional': True,
        'context_vars': ['name', 'period', 'start', 'end', 'total', 'due'],
    },
    'payment_receipt': {
        'label': 'Payment Receipt',
        'channels': ['email', 'push'],
        'optional': False,
        'context_vars': ['name', 'amount', 'date', 'mode', 'balance'],
    },
}

# All channels the platform knows how to speak, regardless of which types
# currently use them (apps.notifications.channels.HANDLERS is the subset
# actually wired up — sms/whatsapp are registered there as no-op stubs).
CHANNELS = ['email', 'sms', 'whatsapp', 'push']


def channels_for(notification_type):
    return NOTIFICATION_TYPES.get(notification_type, {}).get('channels', ['email'])


def is_optional(notification_type):
    return NOTIFICATION_TYPES.get(notification_type, {}).get('optional', True)


def label_for(notification_type):
    return NOTIFICATION_TYPES.get(notification_type, {}).get('label', notification_type)


def context_vars_for(notification_type):
    return NOTIFICATION_TYPES.get(notification_type, {}).get('context_vars', [])
