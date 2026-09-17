from django.urls import reverse

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.models import PushSubscription


class PushSubscriptionAPITests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def test_registers_a_device_token(self):
        response = self.client.post(
            reverse('push-subscription-list'), {'fcm_token': 'abc123', 'device_type': 'web'},
        )

        self.assertEqual(response.status_code, 201)
        with tenant_context(self.tenant.id):
            sub = PushSubscription.objects.get(fcm_token='abc123')
        self.assertEqual(sub.user_id, self.owner.id)
        self.assertEqual(sub.tenant_id, self.tenant.id)

    def test_reregistering_the_same_token_upserts_instead_of_erroring(self):
        self.client.post(reverse('push-subscription-list'), {'fcm_token': 'abc123', 'device_type': 'web'})

        response = self.client.post(
            reverse('push-subscription-list'), {'fcm_token': 'abc123', 'device_type': 'android'},
        )

        self.assertEqual(response.status_code, 200)
        with tenant_context(self.tenant.id):
            self.assertEqual(PushSubscription.objects.filter(fcm_token='abc123').count(), 1)
            self.assertEqual(PushSubscription.objects.get(fcm_token='abc123').device_type, 'android')

    def test_user_only_sees_their_own_subscriptions(self):
        other_owner = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        with tenant_context(other_owner.tenant_id):
            PushSubscription.objects.create(
                tenant_id=other_owner.tenant_id, user=other_owner, fcm_token='other-token', device_type='web',
            )

        response = self.client.get(reverse('push-subscription-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_can_unregister_a_device(self):
        create_response = self.client.post(
            reverse('push-subscription-list'), {'fcm_token': 'abc123', 'device_type': 'web'},
        )
        sub_id = create_response.data['id']

        response = self.client.delete(reverse('push-subscription-detail', args=[sub_id]))

        self.assertEqual(response.status_code, 204)
        with tenant_context(self.tenant.id):
            self.assertFalse(PushSubscription.objects.filter(fcm_token='abc123').exists())
