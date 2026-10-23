from django.core import mail
from django.test import TestCase, override_settings
from django.utils.html import escape

from apps.core.email import render_email, send_templated_email
from apps.core.models import PlatformConfig
from apps.notifications.channels.email import EmailChannel
from apps.notifications.models import NotificationLog

CTA_URL = 'https://app.example.com/reset-password#uid=abc&token=x-y_z'
HOSTILE = '<script>alert("x")</script> & Co'

CONTEXTS = {
    'verify_email': {'name': 'Asha', 'cta_url': CTA_URL, 'valid_hours': 72},
    'password_reset': {'name': 'Asha', 'cta_url': CTA_URL, 'valid_hours': 24},
    'staff_invite': {'name': 'Asha', 'business': 'Sunrise PG', 'cta_url': CTA_URL},
    'login_code': {'name': 'Asha', 'code': '482913', 'minutes': 5},
    'password_changed': {'name': 'Asha', 'reset_url': 'https://app.example.com/forgot-password'},
    'notification': {'subject': 'Invoice issued', 'body': 'Amount due: 2000.00\nDue on 5th.'},
}
CTA_TEMPLATES = ['verify_email', 'password_reset', 'staff_invite']


class EmailTemplateRenderingTests(TestCase):
    def test_every_template_renders_html_and_text_in_every_language(self):
        for template, context in CONTEXTS.items():
            for language in ('en', 'te'):
                with self.subTest(template=template, language=language):
                    html, text = render_email(template, context, language)
                    self.assertTrue(html.lstrip().lower().startswith('<!doctype html>'))
                    self.assertIn(f'lang="{language}"', html)
                    self.assertTrue(text.strip())
                    self.assertNotIn('<html', text)

    def test_cta_templates_carry_the_link_in_html_and_text(self):
        for template in CTA_TEMPLATES:
            with self.subTest(template=template):
                html, text = render_email(template, CONTEXTS[template], 'en')
                self.assertIn(f'href="{escape(CTA_URL)}"', html)
                self.assertIn(CTA_URL, text)

    def test_templates_without_a_cta_have_no_button(self):
        for template in ('login_code', 'password_changed', 'notification'):
            with self.subTest(template=template):
                html, text = render_email(template, CONTEXTS[template], 'en')
                self.assertNotIn('class="btn"', html)

    def test_login_code_text_keeps_the_code_first_and_the_expiry(self):
        _, text = render_email('login_code', CONTEXTS['login_code'], 'en')
        self.assertIn('Your sign-in code is 482913.', text)
        self.assertIn('5 minutes', text)

    def test_telugu_is_translated(self):
        english_phrases = {
            'verify_email': ['Verify email', 'Confirm your email address', 'Welcome'],
            'password_reset': ['Reset password', 'We received a request', 'Hi Asha'],
            'staff_invite': ['Set your password', 'An account was created', 'Hi Asha'],
            'login_code': ['Enter this code', 'It expires in'],
            'password_changed': ['Your password was changed', 'was just changed'],
        }
        for template, phrases in english_phrases.items():
            html, text = render_email(template, CONTEXTS[template], 'te')
            for phrase in phrases:
                with self.subTest(template=template, phrase=phrase):
                    self.assertNotIn(phrase, html)
                    self.assertNotIn(phrase, text)

    def test_html_escapes_untrusted_values(self):
        cases = {
            'staff_invite': {**CONTEXTS['staff_invite'], 'business': HOSTILE, 'name': HOSTILE},
            'password_reset': {**CONTEXTS['password_reset'], 'name': HOSTILE},
            'verify_email': {**CONTEXTS['verify_email'], 'name': HOSTILE},
            'notification': {'subject': HOSTILE, 'body': HOSTILE},
        }
        for template, context in cases.items():
            with self.subTest(template=template):
                html, text = render_email(template, context, 'en')
                self.assertNotIn('<script>', html)
                self.assertIn('&lt;script&gt;', html)
                self.assertIn(HOSTILE, text)  # plain text is not HTML-escaped

    def test_notification_body_keeps_line_breaks_in_html(self):
        html, _ = render_email('notification', CONTEXTS['notification'], 'en')
        self.assertIn('Amount due: 2000.00<br>Due on 5th.', html)

    @override_settings(COMPANY_NAME='', COMPANY_ADDRESS='')
    def test_renders_with_no_company_or_support_details(self):
        PlatformConfig.get()  # blank support fields
        html, text = render_email('verify_email', CONTEXTS['verify_email'], 'en')
        self.assertNotIn('Need help?', html)
        self.assertNotIn('Need help?', text)
        self.assertIn('PGLive', text)

    @override_settings(COMPANY_NAME='Acme Pvt Ltd', COMPANY_ADDRESS='1 MG Road & Co, Hyderabad')
    def test_footer_shows_company_and_support_details(self):
        PlatformConfig.objects.update_or_create(
            pk=1, defaults={'support_email': 'help@pglive.in', 'support_phone': '18001234567'},
        )
        html, text = render_email('verify_email', CONTEXTS['verify_email'], 'en')
        self.assertIn('mailto:help@pglive.in', html)
        self.assertIn('Acme Pvt Ltd', html)
        self.assertIn('1 MG Road &amp; Co, Hyderabad', html)
        self.assertIn('help@pglive.in', text)
        self.assertIn('1 MG Road & Co, Hyderabad', text)

    @override_settings(FRONTEND_BASE_URL='https://www.pglive.in/')
    def test_logo_is_an_absolute_url(self):
        html, _ = render_email('verify_email', CONTEXTS['verify_email'], 'en')
        self.assertIn('src="https://www.pglive.in/brand/pglive-logo.png"', html)


class SendTemplatedEmailTests(TestCase):
    def test_sends_multipart_with_text_body_and_html_alternative(self):
        send_templated_email(
            to='asha@example.com', subject='Hello', template='verify_email',
            context=CONTEXTS['verify_email'], language='en',
        )
        message = mail.outbox[0]
        self.assertEqual(message.to, ['asha@example.com'])
        self.assertEqual(message.subject, 'Hello')
        self.assertIn(CTA_URL, message.body)
        (html, mimetype), = message.alternatives
        self.assertEqual(mimetype, 'text/html')
        self.assertIn('<table', html)

    def test_callable_subject_is_evaluated_in_the_recipients_language(self):
        from django.utils.translation import gettext as _

        send_templated_email(
            to='asha@example.com', subject=lambda: _('Your sign-in code'),
            template='login_code', context=CONTEXTS['login_code'], language='te',
        )
        self.assertNotEqual(mail.outbox[0].subject, 'Your sign-in code')


class NotificationChannelEmailTests(TestCase):
    def test_wraps_the_template_text_in_the_branded_layout(self):
        status, error = EmailChannel().send(
            recipient_email='res@example.com', subject='Receipt', body=HOSTILE,
        )
        self.assertEqual((status, error), (NotificationLog.Status.SENT, ''))
        message = mail.outbox[0]
        self.assertEqual(message.body.splitlines()[0], 'Receipt')
        self.assertIn(HOSTILE, message.body)
        (html, _mimetype), = message.alternatives
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)

    def test_missing_address_is_skipped(self):
        status, _ = EmailChannel().send(recipient_email='', subject='x', body='y')
        self.assertEqual(status, NotificationLog.Status.SKIPPED)
        self.assertEqual(mail.outbox, [])

    def test_delivery_failure_is_reported_not_raised(self):
        with override_settings(EMAIL_BACKEND='apps.core.test_email_templates.BrokenBackend'):
            status, error = EmailChannel().send(recipient_email='res@example.com', subject='x', body='y')
        self.assertEqual(status, NotificationLog.Status.FAILED)
        self.assertIn('smtp down', error)


class BrokenBackend:
    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError('smtp down')
