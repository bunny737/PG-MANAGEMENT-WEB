import uuid

from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.devices.models import AppInstallation
from apps.notifications.models import PushSubscription

from .base import DevicesAPITestCase, device_payload


class PushSubscriptionInstallationLinkTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def subscribe(self, **extra):
        body = {'fcm_token': 'tok-1', 'device_type': 'android', **extra}
        return self.client.post(reverse('push-subscription-list'), body, format='json')

    def subscription(self, token='tok-1'):
        with tenant_context(self.tenant.id):
            return PushSubscription.objects.get(fcm_token=token)

    def test_links_the_subscription_to_an_existing_install(self):
        payload = device_payload()
        self.register(payload)

        response = self.subscribe(installation_id=payload['installation_id'])

        self.assertEqual(response.status_code, 201)
        self.assertNotIn('installation_id', response.data)  # write-only
        self.assertEqual(
            self.subscription().installation, AppInstallation.objects.get(installation_id=payload['installation_id']),
        )

    def test_unknown_installation_id_is_ignored(self):
        response = self.subscribe(installation_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(self.subscription().installation)

    def test_without_installation_id_behaviour_is_unchanged(self):
        self.assertEqual(self.subscribe().status_code, 201)
        self.assertIsNone(self.subscription().installation)

    def test_invalid_installation_id_is_a_validation_error(self):
        self.assertEqual(self.subscribe(installation_id='nope').status_code, 400)

    def test_resubscribing_without_an_id_keeps_the_existing_link(self):
        payload = device_payload()
        self.register(payload)
        self.subscribe(installation_id=payload['installation_id'])

        response = self.subscribe()

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.subscription().installation)

    def test_purging_the_install_keeps_the_subscription(self):
        payload = device_payload()
        self.register(payload)
        self.subscribe(installation_id=payload['installation_id'])

        with tenant_context(None, is_super_admin=True):
            AppInstallation.objects.all().delete()

        self.assertIsNone(self.subscription().installation)

    def test_retention_purge_with_a_linked_subscription_succeeds(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.devices.tasks import purge_stale_app_data

        payload = device_payload()
        self.register(payload)
        self.subscribe(installation_id=payload['installation_id'])
        AppInstallation.objects.update(last_seen_at=timezone.now() - timedelta(days=200))

        purge_stale_app_data()

        self.assertEqual(AppInstallation.objects.count(), 0)
        self.assertIsNone(self.subscription().installation)

    def test_link_is_tenant_safe_other_tenants_cannot_see_the_subscription(self):
        payload = device_payload()
        self.register(payload)
        self.subscribe(installation_id=payload['installation_id'])
        other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.authenticate(other)

        response = self.client.get(reverse('push-subscription-list'))

        self.assertEqual(response.data, [])
        with tenant_context(other.tenant_id):
            self.assertEqual(PushSubscription.objects.count(), 0)
