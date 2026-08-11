from django.urls import reverse
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from .base import STRONG_PASSWORD, AuthAPITestCase


class TenantEndpointTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_owner_can_update_tenant_default_language(self):
        self.authenticate(self.owner)
        url = reverse('tenant-current')
        response = self.client.patch(url, {'default_language': 'hi'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['default_language'], 'hi')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.default_language, 'hi')

        # Check audit log under tenant context (AuditLog has RLS enabled)
        with tenant_context(self.tenant.id):
            log = AuditLog.objects.filter(action='tenant.updated').first()
            self.assertIsNotNone(log)
            self.assertEqual(log.before, {'default_language': 'en'})
            self.assertEqual(log.after, {'default_language': 'hi'})

    def test_receptionist_cannot_update_tenant_default_language(self):
        receptionist = self.create_user(self.tenant, Role.RECEPTIONIST, 'reception@example.com')
        self.authenticate(receptionist)
        url = reverse('tenant-current')
        response = self.client.patch(url, {'default_language': 'te'})

        self.assertEqual(response.status_code, 403)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.default_language, 'en')

    def test_accept_language_header_honored_on_validation_error(self):
        # Signup's duplicate-email check (SignupSerializer.validate_email) is a
        # plain serializers.Serializer, not a ModelSerializer — so this is our
        # own gettext-wrapped message, not DRF's auto-generated UniqueValidator
        # text (which ships no `te` translation and would stay English
        # regardless of the header). `te` is used because it's the MVP-active
        # translated language (owner decision 2026-08-11) with a compiled
        # catalog, proving translation actually happened, not just that the
        # header was accepted.
        self.create_user(self.tenant, Role.OWNER, 'taken@example.com')

        url = reverse('auth-signup')
        response = self.client.post(
            url,
            {
                'business_name': 'New Biz',
                'first_name': 'Test',
                'email': 'taken@example.com',
                'password': STRONG_PASSWORD,
            },
            HTTP_ACCEPT_LANGUAGE='te'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)
        self.assertEqual(str(response.data['email'][0]), 'ఈ ఇమెయిల్‌తో ఖాతా ఇప్పటికే ఉంది.')
