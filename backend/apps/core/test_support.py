from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.tests.base import AuthAPITestCase
from apps.devices.models import AppVersionPolicy
from apps.devices.tests.base import app_headers

from .models import PlatformConfig


class SupportContactAPITests(APITestCase):
    url = reverse('support-contact')

    def configure(self, **fields):
        config = PlatformConfig.get()
        for name, value in fields.items():
            setattr(config, name, value)
        config.full_clean()
        config.save()

    def test_unconfigured_returns_nulls_and_does_not_create_the_row(self):
        PlatformConfig.objects.all().delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            'email': None, 'phone': None, 'whatsapp': None, 'whatsapp_url': None,
            'website': None, 'hours': None,
        })
        self.assertFalse(PlatformConfig.objects.exists())

    def test_returns_configured_channels(self):
        self.configure(
            support_email='help@pgmate.example', support_phone='919876543210',
            support_whatsapp='919876543211', support_website='https://pgmate.example/help',
            support_hours='Mon–Sat, 9am–7pm IST',
        )
        data = self.client.get(self.url).data
        self.assertEqual(data['email'], 'help@pgmate.example')
        self.assertEqual(data['phone'], '919876543210')
        self.assertEqual(data['whatsapp'], '919876543211')
        self.assertEqual(data['whatsapp_url'], 'https://wa.me/919876543211')
        self.assertEqual(data['website'], 'https://pgmate.example/help')
        self.assertEqual(data['hours'], 'Mon–Sat, 9am–7pm IST')

    def test_unset_channel_is_null_while_others_are_served(self):
        self.configure(support_email='help@pgmate.example')
        data = self.client.get(self.url).data
        self.assertEqual(data['email'], 'help@pgmate.example')
        self.assertIsNone(data['phone'])
        self.assertIsNone(data['whatsapp_url'])

    def test_edit_takes_effect_without_a_deploy(self):
        self.configure(support_email='old@pgmate.example')
        self.assertEqual(self.client.get(self.url).data['email'], 'old@pgmate.example')
        self.configure(support_email='new@pgmate.example')
        self.assertEqual(self.client.get(self.url).data['email'], 'new@pgmate.example')

    def test_is_public_and_ignores_a_bad_token(self):
        self.configure(support_email='help@pgmate.example')
        response = self.client.get(self.url, HTTP_AUTHORIZATION='Bearer not-a-token')
        self.assertEqual(response.status_code, 200)

    def test_response_is_cacheable(self):
        self.assertIn('max-age=', self.client.get(self.url)['Cache-Control'])

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    def test_numbers_must_be_digits_with_country_code(self):
        for bad in ('+919876543210', '98765 43210', 'abc', '12345'):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.configure(support_phone=bad)
        with self.assertRaises(ValidationError):
            self.configure(support_whatsapp='+919876543210')


class SupportContactGateTests(AuthAPITestCase):
    """Support must stay reachable exactly when users need it most."""

    @override_settings(APP_VERSION_ENFORCEMENT='on')
    def test_served_to_an_outdated_build(self):
        AppVersionPolicy.objects.create(
            platform='android', flavor='prod', min_build=50, latest_build=50,
            maintenance_enabled=True,
        )
        response = self.client.get(reverse('support-contact'), **app_headers(build=1))
        self.assertEqual(response.status_code, 200)


class SupportContactSchemaTests(APITestCase):
    def test_openapi_documents_every_response_field(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        ok = schema['paths']['/api/v1/support/']['get']['responses']['200']
        ref = ok['content']['application/json']['schema']['$ref'].rsplit('/', 1)[1]
        properties = schema['components']['schemas'][ref]['properties']
        self.assertEqual(set(properties), {'email', 'phone', 'whatsapp', 'whatsapp_url', 'website', 'hours'})
