from urllib.parse import urlencode

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

    def test_replaces_swaps_the_old_subscription_atomically(self):
        old = self.client.post(reverse('push-subscription-list'), {'fcm_token': 'old', 'device_type': 'web'})

        response = self.client.post(
            reverse('push-subscription-list'),
            {'fcm_token': 'new', 'device_type': 'web', 'replaces': old.data['id']}, format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn('replaces', response.data)  # write-only
        with tenant_context(self.tenant.id):
            self.assertEqual(list(PushSubscription.objects.values_list('fcm_token', flat=True)), ['new'])

    def test_replaces_cannot_delete_another_users_subscription(self):
        other_owner = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        with tenant_context(other_owner.tenant_id):
            theirs = PushSubscription.objects.create(
                tenant_id=other_owner.tenant_id, user=other_owner, fcm_token='theirs', device_type='web',
            )

        self.client.post(
            reverse('push-subscription-list'),
            {'fcm_token': 'mine', 'device_type': 'web', 'replaces': str(theirs.id)}, format='json',
        )

        with tenant_context(is_super_admin=True):
            self.assertTrue(PushSubscription.objects.filter(pk=theirs.pk).exists())

    def test_cannot_delete_another_users_subscription(self):
        other_owner = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        with tenant_context(other_owner.tenant_id):
            theirs = PushSubscription.objects.create(
                tenant_id=other_owner.tenant_id, user=other_owner, fcm_token='theirs', device_type='web',
            )

        response = self.client.delete(reverse('push-subscription-detail', args=[theirs.id]))

        self.assertEqual(response.status_code, 404)
        with tenant_context(is_super_admin=True):
            self.assertTrue(PushSubscription.objects.filter(pk=theirs.pk).exists())

    def test_token_last_used_under_another_tenant_moves_to_the_new_user(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other@example.com')
        self.authenticate(other_owner)
        self.client.post(reverse('push-subscription-list'), {'fcm_token': 'shared-device', 'device_type': 'web'})

        # Same browser, now logged in as the first tenant's owner.
        self.authenticate(self.owner)
        response = self.client.post(
            reverse('push-subscription-list'), {'fcm_token': 'shared-device', 'device_type': 'web'},
        )

        self.assertEqual(response.status_code, 201, response.data)
        with tenant_context(is_super_admin=True):
            sub = PushSubscription.objects.get(fcm_token='shared-device')
        self.assertEqual(sub.user_id, self.owner.id)
        self.assertEqual(sub.tenant_id, self.tenant.id)


class ConditionalPushSubscriptionDeleteTests(AuthAPITestCase):
    """A web client's cleanup DELETE can arrive late. The same account turning push off and on
    again gets the same row id back from the token upsert, so the late DELETE must be able to say
    "only if nobody re-registered since"."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def _register(self):
        return self.client.post(reverse('push-subscription-list'), {'fcm_token': 'abc123', 'device_type': 'web'})

    def _delete(self, sub_id, last_seen_at=None):
        url = reverse('push-subscription-detail', args=[sub_id])
        if last_seen_at:
            url += '?' + urlencode({'if_last_seen_at': last_seen_at})
        return self.client.delete(url)

    def test_conditional_delete_removes_the_row_when_nothing_changed(self):
        created = self._register().data

        response = self._delete(created['id'], created['last_seen_at'])

        self.assertEqual(response.status_code, 204)
        with tenant_context(self.tenant.id):
            self.assertFalse(PushSubscription.objects.filter(pk=created['id']).exists())

    def test_late_delete_does_not_remove_a_row_that_was_registered_again(self):
        first = self._register().data
        again = self._register().data  # same token, same account: same row id, newer last_seen_at
        self.assertEqual(again['id'], first['id'])
        self.assertNotEqual(again['last_seen_at'], first['last_seen_at'])

        response = self._delete(first['id'], first['last_seen_at'])  # the stale cleanup arrives

        self.assertEqual(response.status_code, 412)
        with tenant_context(self.tenant.id):
            self.assertTrue(PushSubscription.objects.filter(pk=first['id']).exists())

    def test_delete_without_the_condition_is_unchanged(self):
        created = self._register().data
        self._register()

        response = self._delete(created['id'])

        self.assertEqual(response.status_code, 204)

    def test_a_malformed_condition_is_a_400_and_deletes_nothing(self):
        created = self._register().data

        response = self._delete(created['id'], 'not-a-date')

        self.assertEqual(response.status_code, 400)
        with tenant_context(self.tenant.id):
            self.assertTrue(PushSubscription.objects.filter(pk=created['id']).exists())

    def test_conditional_delete_still_cannot_touch_another_users_row(self):
        other_owner = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        with tenant_context(other_owner.tenant_id):
            theirs = PushSubscription.objects.create(
                tenant_id=other_owner.tenant_id, user=other_owner, fcm_token='theirs', device_type='web',
            )

        response = self._delete(theirs.id, theirs.last_seen_at.isoformat())

        self.assertEqual(response.status_code, 404)
        with tenant_context(is_super_admin=True):
            self.assertTrue(PushSubscription.objects.filter(pk=theirs.pk).exists())
