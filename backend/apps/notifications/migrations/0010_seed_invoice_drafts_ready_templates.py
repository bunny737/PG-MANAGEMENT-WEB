# Seeds wording for `invoice_drafts_ready` — the Owner / invoice-manager
# summary sent after the daily automatic-billing sweep (Module 08). Same
# get_or_create pattern as 0003, so a Super Admin's later edits survive.
import uuid

from django.db import migrations

TEMPLATES = [
    dict(
        notification_type='invoice_drafts_ready', channel='email', language='en',
        subject='Invoices drafted for {{ property }}',
        body=(
            'Dear {{ name }},\n\n'
            'Automatic billing ran for {{ property }} on {{ date }}.\n'
            '{% if created %}New draft invoices: {{ created }} ({{ scheduled }} will be issued '
            'automatically on their billing date).\n{% endif %}'
            '{% if needs_confirmation %}Invoices waiting for your confirmation: {{ needs_confirmation }}.\n{% endif %}'
            '{% if gaps %}Unbilled periods to invoice by hand: {{ gaps }}.\n{% endif %}'
            '\nReview them under Billing > Invoices > Needs review.\n\n'
            'Thank you.'
        ),
    ),
    dict(
        notification_type='invoice_drafts_ready', channel='email', language='te',
        subject='{{ property }} కోసం ఇన్‌వాయిస్‌లు సిద్ధం చేయబడ్డాయి',
        body=(
            'ప్రియమైన {{ name }},\n\n'
            '{{ date }} న {{ property }} కోసం ఆటోమేటిక్ బిల్లింగ్ నడిచింది.\n'
            '{% if created %}కొత్త డ్రాఫ్ట్ ఇన్‌వాయిస్‌లు: {{ created }} ({{ scheduled }} వాటి బిల్లింగ్ తేదీన '
            'ఆటోమేటిక్‌గా జారీ చేయబడతాయి).\n{% endif %}'
            '{% if needs_confirmation %}మీ నిర్ధారణ కోసం వేచి ఉన్న ఇన్‌వాయిస్‌లు: {{ needs_confirmation }}.\n{% endif %}'
            '{% if gaps %}మీరే ఇన్‌వాయిస్ చేయవలసిన బిల్ చేయని కాలాలు: {{ gaps }}.\n{% endif %}'
            '\nబిల్లింగ్ > ఇన్‌వాయిస్‌లు > సమీక్ష అవసరం లో వాటిని చూడండి.\n\n'
            'ధన్యవాదాలు.'
        ),
    ),
    dict(
        notification_type='invoice_drafts_ready', channel='push', language='en',
        subject='Invoices drafted',
        body=(
            '{{ property }}: {{ created }} new draft(s), {{ needs_confirmation }} need your confirmation.'
            '{% if gaps %} Unbilled: {{ gaps }}.{% endif %}'
        ),
    ),
    dict(
        notification_type='invoice_drafts_ready', channel='push', language='te',
        subject='ఇన్‌వాయిస్‌లు సిద్ధం',
        body=(
            '{{ property }}: {{ created }} కొత్త డ్రాఫ్ట్(లు), {{ needs_confirmation }} మీ నిర్ధారణ అవసరం.'
            '{% if gaps %} బిల్ చేయనివి: {{ gaps }}.{% endif %}'
        ),
    ),
]


def seed_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('notifications', 'NotificationTemplate')
    for entry in TEMPLATES:
        NotificationTemplate.objects.get_or_create(
            notification_type=entry['notification_type'],
            channel=entry['channel'],
            language=entry['language'],
            defaults={
                'id': uuid.uuid4(),
                'subject': entry['subject'],
                'body': entry['body'],
                'is_active': True,
            },
        )


def remove_seeded_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('notifications', 'NotificationTemplate')
    for entry in TEMPLATES:
        NotificationTemplate.objects.filter(
            notification_type=entry['notification_type'],
            channel=entry['channel'],
            language=entry['language'],
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0009_alter_notificationlog_notification_type'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_seeded_templates),
    ]
