from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog, NotificationTemplate
from apps.notifications.services import notify, render_template


class RenderTemplateFallbackTests(AuthAPITestCase):
    """render_template must degrade to English rather than crash or send
    nothing when the requested language has no template (invariant 7)."""

    def test_renders_exact_language_match(self):
        NotificationTemplate.objects.create(
            notification_type='welcome', channel='email', language='te',
            subject='తెలుగు విషయం {{ name }}', body='హలో {{ name }}',
        )
        subject, body = render_template(
            notification_type='welcome', channel='email', language='te',
            context={'name': 'రమేష్'},
        )
        self.assertEqual(subject, 'తెలుగు విషయం రమేష్')
        self.assertEqual(body, 'హలో రమేష్')

    def test_falls_back_to_english_when_language_missing(self):
        NotificationTemplate.objects.create(
            notification_type='welcome', channel='email', language='en',
            subject='Hello {{ name }}', body='Welcome {{ name }}',
        )
        subject, body = render_template(
            notification_type='welcome', channel='email', language='hi',
            context={'name': 'Ramesh'},
        )
        self.assertEqual(subject, 'Hello Ramesh')
        self.assertEqual(body, 'Welcome Ramesh')

    def test_returns_none_when_no_template_in_any_language(self):
        subject, body = render_template(
            notification_type='nonexistent', channel='email', language='en', context={},
        )
        self.assertIsNone(subject)
        self.assertIsNone(body)

    def test_inactive_template_is_not_used(self):
        NotificationTemplate.objects.create(
            notification_type='welcome', channel='email', language='en',
            subject='Old', body='Old body', is_active=False,
        )
        subject, body = render_template(
            notification_type='welcome', channel='email', language='en', context={},
        )
        self.assertIsNone(subject)
        self.assertIsNone(body)


class NotifyDispatchTests(AuthAPITestCase):
    """services.notify() is the generic entry point every trigger site and
    task now calls — verify it logs one row per applicable channel and
    handles a missing template as a clean skip, not a crash."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        # invoice_issued/email/en already exists via the 0003 seed migration
        # (production content) — update_or_create so this test controls its
        # own fixture content regardless, and stays valid if that seed changes.
        NotificationTemplate.objects.update_or_create(
            notification_type='invoice_issued', channel='email', language='en',
            defaults={'subject': 'Invoice {{ period }}', 'body': 'Total {{ total }}', 'is_active': True},
        )
        # No push template for invoice_issued/en, though — the seed migration
        # DOES provide one, so delete it to exercise the "no active template" path.
        NotificationTemplate.objects.filter(
            notification_type='invoice_issued', channel='push', language='en',
        ).delete()

    def test_logs_one_row_per_applicable_channel(self):
        with tenant_context(self.tenant.id):
            results = notify(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={'period': 'July', 'total': '5000'},
                reference='test:1',
            )
        # registry.py: invoice_issued -> ['email', 'push']
        self.assertEqual(len(results), 2)
        statuses = {r.channel: r.status for r in results}
        self.assertEqual(statuses['email'], NotificationLog.Status.SENT)
        self.assertEqual(statuses['push'], NotificationLog.Status.SKIPPED)

    def test_missing_template_logs_skipped_not_an_exception(self):
        with tenant_context(self.tenant.id):
            results = notify(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={}, channels=['push'], reference='test:2',
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, NotificationLog.Status.SKIPPED)
        self.assertIn('No active template', results[0].note)

    def test_recipient_user_is_stamped_on_the_log_for_a_real_user(self):
        with tenant_context(self.tenant.id):
            results = notify(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={'period': 'July', 'total': '5000'},
                channels=['email'], reference='test:3',
            )
        self.assertEqual(results[0].recipient_user_id, self.owner.id)

    def test_channel_with_registered_handler_but_no_template_is_skipped(self):
        # 'sms' has a registered handler (channels/sms.py) but no active
        # template — must not raise, must log a clean skip.
        with tenant_context(self.tenant.id):
            results = notify(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={}, channels=['sms'], reference='test:4',
            )
        self.assertEqual(results[0].status, NotificationLog.Status.SKIPPED)

    def test_channel_with_no_registered_handler_is_silently_skipped(self):
        # A channel neither built nor templated (hypothetical future one) —
        # notify() must skip it entirely, not log or raise.
        with tenant_context(self.tenant.id):
            results = notify(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={}, channels=['carrier_pigeon'], reference='test:5',
            )
        self.assertEqual(results, [])
