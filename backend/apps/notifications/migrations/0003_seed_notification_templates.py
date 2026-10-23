# Seeds NotificationTemplate rows so behavior is unchanged the moment this
# ships — nothing breaks if a Super Admin hasn't touched the admin yet.
# Email en/te bodies are ported verbatim (converted from %(x)s to {{ x }})
# from the original apps.notifications.emails module and the existing
# locale/te/LC_MESSAGES/django.po translations, so wording doesn't drift.
# Push bodies are new content (push didn't exist before this migration).
import uuid

from django.db import migrations

TEMPLATES = [
    # invoice_issued
    dict(
        notification_type='invoice_issued', channel='email', language='en',
        subject='Invoice for {{ period }}',
        body=(
            'Dear {{ name }},\n\n'
            'Your invoice for the period {{ start }} to {{ end }} has been issued.\n'
            'Amount due: {{ total }}\n'
            'Due date: {{ due }}\n\n'
            'Thank you.'
        ),
    ),
    dict(
        notification_type='invoice_issued', channel='email', language='te',
        subject='{{ period }} కోసం ఇన్‌వాయిస్',
        body=(
            'ప్రియమైన {{ name }},\n\n'
            '{{ start }} నుండి {{ end }} వరకు కాలానికి మీ ఇన్‌వాయిస్ జారీ చేయబడింది.\n'
            'చెల్లించవలసిన మొత్తం: {{ total }}\n'
            'చెల్లించవలసిన తేదీ: {{ due }}\n\n'
            'ధన్యవాదాలు.'
        ),
    ),
    dict(
        notification_type='invoice_issued', channel='push', language='en',
        subject='Invoice issued',
        body='Your invoice for {{ period }} is ready. Amount due: {{ total }}, due {{ due }}.',
    ),
    dict(
        notification_type='invoice_issued', channel='push', language='te',
        subject='ఇన్‌వాయిస్ జారీ చేయబడింది',
        body='{{ period }} కోసం మీ ఇన్‌వాయిస్ సిద్ధంగా ఉంది. చెల్లించవలసిన మొత్తం: {{ total }}, గడువు {{ due }}.',
    ),
    # payment_receipt
    dict(
        notification_type='payment_receipt', channel='email', language='en',
        subject='Payment receipt — {{ amount }} received',
        body=(
            'Dear {{ name }},\n\n'
            'We have received your payment of {{ amount }} on {{ date }} via {{ mode }}.\n'
            'Remaining balance on this invoice: {{ balance }}\n\n'
            'Thank you.'
        ),
    ),
    dict(
        notification_type='payment_receipt', channel='email', language='te',
        subject='చెల్లింపు రసీదు — {{ amount }} అందుకోబడింది',
        body=(
            'ప్రియమైన {{ name }},\n\n'
            '{{ date }} న {{ mode }} ద్వారా మీ {{ amount }} చెల్లింపును మేము అందుకున్నాము.\n'
            'ఈ ఇన్‌వాయిస్‌పై మిగిలిన బాకీ: {{ balance }}\n\n'
            'ధన్యవాదాలు.'
        ),
    ),
    dict(
        notification_type='payment_receipt', channel='push', language='en',
        subject='Payment received',
        body='We received your payment of {{ amount }} on {{ date }}. Remaining balance: {{ balance }}.',
    ),
    dict(
        notification_type='payment_receipt', channel='push', language='te',
        subject='చెల్లింపు అందుకోబడింది',
        body='{{ date }} న మీ {{ amount }} చెల్లింపును మేము అందుకున్నాము. మిగిలిన బాకీ: {{ balance }}.',
    ),
    # trial_expiry_reminder
    dict(
        notification_type='trial_expiry_reminder', channel='email', language='en',
        subject='Your trial ends in {{ days }} day(s)',
        body=(
            'Dear {{ name }},\n\n'
            'Your free trial of the platform for {{ business }} ends in {{ days }} day(s), '
            'on {{ end_date }}. Choose a plan to keep using the platform without interruption.\n\n'
            'Thank you.'
        ),
    ),
    dict(
        notification_type='trial_expiry_reminder', channel='email', language='te',
        subject='మీ ట్రయల్ {{ days }} రోజు(ల)లో ముగుస్తుంది',
        body=(
            'ప్రియమైన {{ name }},\n\n'
            '{{ business }} కోసం ప్లాట్‌ఫారమ్ యొక్క మీ ఉచిత ట్రయల్ {{ days }} రోజు(ల)లో, {{ end_date }} న ముగుస్తుంది. '
            'అంతరాయం లేకుండా ప్లాట్‌ఫారమ్‌ను ఉపయోగించడం కొనసాగించడానికి ఒక ప్లాన్‌ను ఎంచుకోండి.\n\n'
            'ధన్యవాదాలు.'
        ),
    ),
    dict(
        notification_type='trial_expiry_reminder', channel='push', language='en',
        subject='Trial ending soon',
        body='Your trial ends in {{ days }} day(s) on {{ end_date }}. Choose a plan to continue.',
    ),
    dict(
        notification_type='trial_expiry_reminder', channel='push', language='te',
        subject='ట్రయల్ త్వరలో ముగుస్తుంది',
        body='మీ ట్రయల్ {{ days }} రోజు(ల)లో, {{ end_date }} న ముగుస్తుంది. కొనసాగించడానికి ప్లాన్ ఎంచుకోండి.',
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
        ('notifications', '0002_notificationlog_channel_notificationtemplate_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_seeded_templates),
    ]
