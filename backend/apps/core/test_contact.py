"""POST /api/v1/public/contact/ — the website contact form — and its Django-admin inbox.

ContactMessage is platform-level (no tenant_id, no RLS): the sender is an anonymous
prospect. Tests prove the public contract, the abuse controls, and the admin rules."""
import json
from unittest import mock

from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.tests.base import AuthAPITestCase
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.devices.models import AppVersionPolicy
from apps.devices.tests.base import app_headers

from .models import ContactMessage


def payload(**overrides):
    return {
        'name': 'Ravi Kumar',
        'email': 'Ravi@Example.com',
        'phone': '+91 98765 43210',
        'message': 'I run a 60-bed PG in Hyderabad and would like early access.',
        **overrides,
    }


class ContactMessageAPITests(APITestCase):
    url = reverse('contact-message')

    def setUp(self):
        cache.clear()  # throttle counters live in the cache
        # Generous limits by default so tests that post many times are not throttled;
        # the throttle tests below lower them explicitly.
        patcher = mock.patch.dict(
            SimpleRateThrottle.THROTTLE_RATES,
            {"contact_message": "1000/hour", "contact_message_email": "1000/hour"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, data=None, **extra):
        return self.client.post(self.url, data if data is not None else payload(), format='json', **extra)

    # --- happy path ------------------------------------------------------------

    def test_stores_the_message_and_acknowledges_it(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data, {'status': 'received'})
        message = ContactMessage.objects.get()
        self.assertEqual(message.name, 'Ravi Kumar')
        self.assertEqual(message.email, 'ravi@example.com')  # normalised
        self.assertEqual(message.phone, '+91 98765 43210')
        self.assertEqual(message.status, ContactMessage.Status.NEW)
        self.assertIsNone(message.handled_at)

    def test_phone_is_optional(self):
        data = payload()
        del data['phone']
        self.assertEqual(self.post(data).status_code, 201)
        self.assertEqual(ContactMessage.objects.get().phone, '')

    def test_text_fields_are_trimmed(self):
        self.post(payload(name='  Ravi Kumar  ', message='   Please call me back about pricing.   '))
        message = ContactMessage.objects.get()
        self.assertEqual(message.name, 'Ravi Kumar')
        self.assertEqual(message.message, 'Please call me back about pricing.')

    def test_records_client_ip_and_language(self):
        self.post(REMOTE_ADDR='203.0.113.9', HTTP_ACCEPT_LANGUAGE='te')
        message = ContactMessage.objects.get()
        self.assertEqual(message.ip_address, '203.0.113.9')
        self.assertEqual(message.language, 'te')

    def test_uses_the_forwarded_client_address(self):
        self.post(HTTP_X_FORWARDED_FOR='198.51.100.7, 10.0.0.1')
        self.assertEqual(ContactMessage.objects.get().ip_address, '198.51.100.7')

    def test_a_garbage_forwarded_address_never_reaches_the_ip_column(self):
        self.assertEqual(self.post(HTTP_X_FORWARDED_FOR='not-an-ip').status_code, 201)
        self.assertIsNone(ContactMessage.objects.get().ip_address)

    # --- validation ------------------------------------------------------------

    def test_field_validation(self):
        cases = {
            'name': ['', 'A'],
            'email': ['', 'not-an-email', 'a@b'],
            'message': ['', 'too short', 'x' * 2001],
            'phone': ['abc', '12345', '+' + '9' * 25],
        }
        for field, bad_values in cases.items():
            for bad in bad_values:
                with self.subTest(field=field, value=bad[:20]):
                    response = self.post(payload(**{field: bad}))
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)
        self.assertFalse(ContactMessage.objects.exists())

    def test_required_fields(self):
        for field in ('name', 'email', 'message'):
            with self.subTest(field=field):
                data = payload()
                del data[field]
                self.assertEqual(self.post(data).status_code, 400)

    def test_sender_cannot_set_server_side_fields(self):
        self.post(payload(status='handled', ip_address='1.2.3.4', handled_at='2020-01-01T00:00:00Z', id='x'))
        message = ContactMessage.objects.get()
        self.assertEqual(message.status, ContactMessage.Status.NEW)
        self.assertIsNone(message.handled_at)
        self.assertNotEqual(message.ip_address, '1.2.3.4')

    # --- abuse controls --------------------------------------------------------

    def test_honeypot_looks_like_success_but_stores_nothing(self):
        response = self.post(payload(website='http://spam.example'))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {'status': 'received'})
        self.assertFalse(ContactMessage.objects.exists())

    def test_empty_honeypot_is_a_normal_submission(self):
        self.assertEqual(self.post(payload(website='')).status_code, 201)
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_per_ip_throttle(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'contact_message': '2/hour'}):
            for n in range(2):
                self.assertEqual(self.post(payload(email=f'p{n}@example.com'), REMOTE_ADDR='203.0.113.5').status_code, 201)
            response = self.post(payload(email='p9@example.com'), REMOTE_ADDR='203.0.113.5')
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response)
            # Another visitor is unaffected.
            self.assertEqual(self.post(payload(email='q@example.com'), REMOTE_ADDR='203.0.113.6').status_code, 201)

    def test_per_email_throttle_holds_when_the_ip_changes(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'contact_message_email': '2/hour'}):
            self.assertEqual(self.post(payload(email='Same@Example.com'), REMOTE_ADDR='10.0.0.1').status_code, 201)
            self.assertEqual(self.post(payload(email='same@example.com'), REMOTE_ADDR='10.0.0.2').status_code, 201)
            response = self.post(payload(email=' SAME@example.com'), REMOTE_ADDR='10.0.0.3')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(ContactMessage.objects.count(), 2)

    def test_oversized_body_is_rejected_before_parsing(self):
        response = self.post(payload(message='x' * 20_000))
        self.assertEqual(response.status_code, 413)
        self.assertFalse(ContactMessage.objects.exists())

    def test_malformed_json_is_a_client_error_not_a_crash(self):
        response = self.client.post(self.url, data='{not json', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    # --- access ----------------------------------------------------------------

    def test_is_public_and_ignores_a_bad_token(self):
        self.assertEqual(self.post(HTTP_AUTHORIZATION='Bearer not-a-token').status_code, 201)

    def test_write_only(self):
        self.post()
        for method in ('get', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)

    def test_response_never_echoes_stored_data(self):
        body = json.dumps(self.post().data)
        self.assertNotIn('ravi', body.lower())

    def test_is_platform_level_with_no_tenant_column(self):
        # Invariant 1 does not apply: the sender is anonymous, there is no tenant to scope to.
        names = {field.name for field in ContactMessage._meta.get_fields()}
        self.assertNotIn('tenant', names)
        self.assertNotIn('tenant_id', names)


class ContactMessageRateTests(APITestCase):
    """Separate from the API tests, which loosen the limits so they can post freely."""

    def test_default_rates_match_the_spec(self):
        rates = SimpleRateThrottle.THROTTLE_RATES
        self.assertEqual(rates['contact_message'], '5/hour')
        self.assertEqual(rates['contact_message_email'], '3/hour')


class ContactMessageGateTests(AuthAPITestCase):
    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_reachable_from_an_outdated_app_build(self):
        AppVersionPolicy.objects.create(
            platform='android', flavor='prod', min_build=50, latest_build=50, maintenance_enabled=True,
        )
        response = self.client.post(reverse('contact-message'), payload(), format='json', **app_headers(build=1))
        self.assertEqual(response.status_code, 201)


class ContactMessageSchemaTests(APITestCase):
    def test_openapi_documents_the_request_and_response(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        post = schema['paths']['/api/v1/public/contact/']['post']
        self.assertIn('201', post['responses'])
        request_ref = post['requestBody']['content']['application/json']['schema']['$ref'].rsplit('/', 1)[1]
        self.assertEqual(
            set(schema['components']['schemas'][request_ref]['properties']),
            {'name', 'email', 'phone', 'message', 'website'},
        )


class ContactMessageAdminTests(AuthAPITestCase):
    """Django admin is the inbox: content is read-only, status moves only through
    audited actions, and a delete is audited too."""

    def setUp(self):
        super().setUp()
        self.staff = self.create_user(
            None, Role.SUPER_ADMIN, 'inbox@platform.example.com', is_staff=True, is_superuser=True,
        )
        self.admin_client = Client()
        self.admin_client.force_login(self.staff)
        self.first = ContactMessage.objects.create(name='Asha', email='asha@example.com', message='Pricing question please.')
        self.second = ContactMessage.objects.create(name='Bala', email='bala@example.com', message='Early access request.')

    def audit_actions(self):
        with tenant_context(None, is_super_admin=True):
            # Sorted: only which actions were recorded matters, not the row order.
            return sorted(AuditLog.objects.filter(action__startswith='contact_message.').values_list('action', flat=True))

    def test_changelist_lists_messages_and_search_works(self):
        url = reverse('admin:core_contactmessage_changelist')
        page = self.admin_client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'asha@example.com')
        self.assertContains(page, 'bala@example.com')
        found = self.admin_client.get(url, {'q': 'Pricing'})
        self.assertContains(found, 'asha@example.com')
        self.assertNotContains(found, 'bala@example.com')

    def test_cannot_add_and_cannot_edit(self):
        self.assertEqual(self.admin_client.get(reverse('admin:core_contactmessage_add')).status_code, 403)
        detail = reverse('admin:core_contactmessage_change', args=[self.first.pk])
        self.assertEqual(self.admin_client.get(detail).status_code, 200)  # view-only page
        self.admin_client.post(detail, {'name': 'Hacked', 'status': 'handled'})
        self.first.refresh_from_db()
        self.assertEqual(self.first.name, 'Asha')
        self.assertEqual(self.first.status, ContactMessage.Status.NEW)

    def run_action(self, action, *messages):
        return self.admin_client.post(
            reverse('admin:core_contactmessage_changelist'),
            {'action': action, '_selected_action': [str(m.pk) for m in messages]},
            follow=True,
        )

    def test_mark_handled_sets_status_and_timestamp_and_is_audited(self):
        response = self.run_action('mark_handled', self.first)
        self.assertContains(response, '1 message updated.')
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.status, ContactMessage.Status.HANDLED)
        self.assertIsNotNone(self.first.handled_at)
        self.assertEqual(self.second.status, ContactMessage.Status.NEW)
        self.assertEqual(self.audit_actions(), ['contact_message.handled'])

    def test_audit_row_keeps_personal_data_out(self):
        self.run_action('mark_handled', self.first)
        with tenant_context(None, is_super_admin=True):
            row = AuditLog.objects.get(action='contact_message.handled')
        payload_text = json.dumps([row.before, row.after])
        self.assertNotIn('asha@example.com', payload_text)
        self.assertNotIn('Pricing question', payload_text)
        self.assertEqual(row.before['status'], 'new')
        self.assertEqual(row.after['status'], 'handled')
        self.assertEqual(row.actor_id, self.staff.pk)

    def test_mark_new_reopens_and_clears_the_timestamp(self):
        self.run_action('mark_handled', self.first)
        self.run_action('mark_new', self.first)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, ContactMessage.Status.NEW)
        self.assertIsNone(self.first.handled_at)
        self.assertEqual(self.audit_actions(), ['contact_message.handled', 'contact_message.reopened'])

    def test_acting_on_a_message_already_in_that_state_writes_no_audit_row(self):
        response = self.run_action('mark_new', self.first)
        self.assertContains(response, '0 messages updated.')
        self.assertEqual(self.audit_actions(), [])

    def test_single_delete_is_audited(self):
        url = reverse('admin:core_contactmessage_delete', args=[self.first.pk])
        self.admin_client.post(url, {'post': 'yes'})
        self.assertFalse(ContactMessage.objects.filter(pk=self.first.pk).exists())
        self.assertEqual(self.audit_actions(), ['contact_message.deleted'])

    def test_bulk_delete_is_audited_per_message(self):
        self.admin_client.post(
            reverse('admin:core_contactmessage_changelist'),
            {'action': 'delete_selected', '_selected_action': [str(self.first.pk), str(self.second.pk)], 'post': 'yes'},
        )
        self.assertFalse(ContactMessage.objects.exists())
        self.assertEqual(self.audit_actions(), ['contact_message.deleted', 'contact_message.deleted'])


class ContactMessageAdminAtomicityTests(ContactMessageAdminTests):
    """Invariant 9: a mutation and its audit record succeed or fail together."""

    def setUp(self):
        super().setUp()
        # A real server turns the failure into a 500; the default client would re-raise it.
        self.admin_client = Client(raise_request_exception=False)
        self.admin_client.force_login(self.staff)

    def failing_audit(self, **kwargs):
        return mock.patch('apps.core.admin.audit_log.record', side_effect=RuntimeError('audit down'), **kwargs)

    def test_status_change_is_rolled_back_when_the_audit_write_fails(self):
        with self.failing_audit():
            response = self.run_action('mark_handled', self.first)
        self.assertEqual(response.status_code, 500)
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, ContactMessage.Status.NEW)
        self.assertIsNone(self.first.handled_at)

    def test_a_status_batch_is_all_or_nothing(self):
        # The first audit write succeeds, the second fails: neither message may change.
        with mock.patch('apps.core.admin.audit_log.record', side_effect=[None, RuntimeError('audit down')]):
            response = self.run_action('mark_handled', self.first, self.second)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            set(ContactMessage.objects.values_list('status', flat=True)), {ContactMessage.Status.NEW},
        )

    def test_single_delete_is_rolled_back_when_the_audit_write_fails(self):
        url = reverse('admin:core_contactmessage_delete', args=[self.first.pk])
        with self.failing_audit():
            response = self.admin_client.post(url, {'post': 'yes'})
        self.assertEqual(response.status_code, 500)
        self.assertTrue(ContactMessage.objects.filter(pk=self.first.pk).exists())

    def test_bulk_delete_is_rolled_back_when_an_audit_write_fails(self):
        with mock.patch('apps.core.admin.audit_log.record', side_effect=[None, RuntimeError('audit down')]):
            response = self.admin_client.post(
                reverse('admin:core_contactmessage_changelist'),
                {'action': 'delete_selected', '_selected_action': [str(self.first.pk), str(self.second.pk)], 'post': 'yes'},
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(ContactMessage.objects.count(), 2)
