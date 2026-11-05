# Module 26: two notification types for residency links (a person asked to be linked to a PG; staff
# answered), plus their seeded wording. Same get_or_create pattern as 0003 / 0010, so a Super
# Admin's later edits survive. Telugu wording has not had a native review (see the module spec).
import uuid

from django.db import migrations, models

TEMPLATES = [
    dict(
        notification_type='residency_link_requested', channel='email', language='en',
        subject='{{ requester }} asked to join {{ property }}',
        body=(
            'Dear {{ name }},\n\n'
            '{{ requester }} asked to be linked to {{ property }} in the app.\n'
            '{% if message %}Message: {{ message }}\n{% endif %}'
            '\nOpen Residents > Link requests to approve it against the right resident record, or reject it.\n\n'
            'Thank you.'
        ),
    ),
    dict(
        notification_type='residency_link_requested', channel='email', language='te',
        subject='{{ requester }} {{ property }}లో చేరడానికి అభ్యర్థించారు',
        body=(
            'ప్రియమైన {{ name }},\n\n'
            '{{ requester }} యాప్‌లో {{ property }}కి లింక్ చేయమని అభ్యర్థించారు.\n'
            '{% if message %}సందేశం: {{ message }}\n{% endif %}'
            '\nసరైన నివాసి రికార్డుతో ఆమోదించడానికి లేదా తిరస్కరించడానికి నివాసితులు > లింక్ అభ్యర్థనలు తెరవండి.\n\n'
            'ధన్యవాదాలు.'
        ),
    ),
    dict(
        notification_type='residency_link_requested', channel='push', language='en',
        subject='New link request',
        body='{{ requester }} asked to join {{ property }}.',
    ),
    dict(
        notification_type='residency_link_requested', channel='push', language='te',
        subject='కొత్త లింక్ అభ్యర్థన',
        body='{{ requester }} {{ property }}లో చేరడానికి అభ్యర్థించారు.',
    ),
    dict(
        notification_type='residency_link_resolved', channel='email', language='en',
        subject='{% if approved %}You are linked to {{ property }}{% else %}Your request for {{ property }}{% endif %}',
        body=(
            'Dear {{ name }},\n\n'
            '{% if approved %}{{ property }} approved your request. You can now see your bills, notices and more in the app.'
            '{% else %}{{ property }} could not link your account.{% if note %} Note: {{ note }}{% endif %}\n'
            'Please contact the PG directly.{% endif %}\n\n'
            'Thank you.'
        ),
    ),
    dict(
        notification_type='residency_link_resolved', channel='email', language='te',
        subject='{% if approved %}మీరు {{ property }}కి లింక్ అయ్యారు{% else %}{{ property }} కోసం మీ అభ్యర్థన{% endif %}',
        body=(
            'ప్రియమైన {{ name }},\n\n'
            '{% if approved %}{{ property }} మీ అభ్యర్థనను ఆమోదించింది. ఇప్పుడు యాప్‌లో మీ బిల్లులు, నోటీసులు మరిన్ని చూడవచ్చు.'
            '{% else %}{{ property }} మీ ఖాతాను లింక్ చేయలేకపోయింది.{% if note %} గమనిక: {{ note }}{% endif %}\n'
            'దయచేసి పిజిని నేరుగా సంప్రదించండి.{% endif %}\n\n'
            'ధన్యవాదాలు.'
        ),
    ),
    dict(
        notification_type='residency_link_resolved', channel='push', language='en',
        subject='{% if approved %}Linked{% else %}Request not approved{% endif %}',
        body='{% if approved %}{{ property }} approved your request.{% else %}{{ property }} could not link your account.{% endif %}',
    ),
    dict(
        notification_type='residency_link_resolved', channel='push', language='te',
        subject='{% if approved %}లింక్ అయింది{% else %}అభ్యర్థన ఆమోదించబడలేదు{% endif %}',
        body='{% if approved %}{{ property }} మీ అభ్యర్థనను ఆమోదించింది.{% else %}{{ property }} మీ ఖాతాను లింక్ చేయలేకపోయింది.{% endif %}',
    ),
]


def seed_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('notifications', 'NotificationTemplate')
    for entry in TEMPLATES:
        NotificationTemplate.objects.get_or_create(
            notification_type=entry['notification_type'], channel=entry['channel'], language=entry['language'],
            defaults={'id': uuid.uuid4(), 'subject': entry['subject'], 'body': entry['body'], 'is_active': True},
        )


def remove_seeded_templates(apps, schema_editor):
    NotificationTemplate = apps.get_model('notifications', 'NotificationTemplate')
    for entry in TEMPLATES:
        NotificationTemplate.objects.filter(
            notification_type=entry['notification_type'], channel=entry['channel'], language=entry['language'],
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0010_seed_invoice_drafts_ready_templates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationlog',
            name='notification_type',
            field=models.CharField(choices=[('welcome', 'Welcome'), ('trial_expiry_reminder', 'Trial Expiry Reminder'), ('invoice_issued', 'Invoice Issued'), ('payment_receipt', 'Payment Receipt'), ('invoice_drafts_ready', 'Invoice Drafts Ready'), ('residency_link_requested', 'Residency Link Requested'), ('residency_link_resolved', 'Residency Link Resolved')], max_length=50),
        ),
        migrations.RunPython(seed_templates, remove_seeded_templates),
    ]
