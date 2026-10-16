"""POST /devices/ keeps notifications.PushSubscription (the one record push
delivery reads) in step with the device, and only authenticated callers can
remove subscriptions — see apps.devices.services._reconcile_push_subscription."""
from unittest import mock

from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.devices.models import AppInstallation
from apps.notifications.models import PushSubscription

from .base import DevicesAPITestCase, device_payload


class PushReconcileTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.payload = device_payload()
        self.seq = 1

    def sync(self, token=None, signed_in=True, user='owner'):
        """One POST /devices/ for self.payload's install, with a rising sync_seq."""
        if user is None:
            self.client.credentials()
        else:
            self.authenticate(getattr(self, user))
        self.seq += 1
        body = device_payload(
            installation_id=self.payload['installation_id'], sync_seq=self.seq, signed_in=signed_in,
            push={'fcm_token': token, 'permission': 'granted' if token else 'denied'},
        )
        return self.register(body)

    def subscriptions(self):
        with tenant_context(None, is_super_admin=True):
            return list(PushSubscription.objects.select_related('installation').order_by('fcm_token'))

    def installation(self):
        return AppInstallation.objects.get(installation_id=self.payload['installation_id'])

    # --- authenticated, token present ---

    def test_first_registration_with_a_token_creates_the_subscription(self):
        response = self.sync(token='tok-a')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['push'], {'subscribed': True})
        [sub] = self.subscriptions()
        self.assertEqual((sub.fcm_token, sub.user_id, sub.tenant_id), ('tok-a', self.owner.id, self.tenant.id))
        self.assertEqual(sub.installation, self.installation())
        self.assertEqual(sub.device_type, 'android')

    def test_update_registration_with_a_token_creates_the_subscription(self):
        self.sync()
        response = self.sync(token='tok-a')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['push'], {'subscribed': True})
        self.assertEqual([s.fcm_token for s in self.subscriptions()], ['tok-a'])

    def test_resync_with_the_same_token_keeps_one_subscription(self):
        self.sync(token='tok-a')
        self.sync(token='tok-a')
        self.assertEqual(len(self.subscriptions()), 1)

    def test_token_rotation_replaces_the_install_subscription(self):
        self.sync(token='tok-a')
        self.sync(token='tok-b')
        self.assertEqual([s.fcm_token for s in self.subscriptions()], ['tok-b'])

    def test_token_moving_to_another_install_moves_the_subscription(self):
        self.sync(token='tok-a')
        other_install = device_payload(push={'fcm_token': 'tok-a', 'permission': 'granted'})
        self.authenticate(self.owner)
        self.register(other_install)

        [sub] = self.subscriptions()
        self.assertEqual(str(sub.installation.installation_id), other_install['installation_id'])

    # --- authenticated, token null (permission revoked) ---

    def test_null_token_on_create_subscribes_nothing(self):
        response = self.sync(token=None)
        self.assertEqual(response.data['push'], {'subscribed': False})
        self.assertEqual(self.subscriptions(), [])

    def test_revoked_permission_removes_the_users_subscription(self):
        self.sync(token='tok-a')
        response = self.sync(token=None)

        self.assertEqual(response.data['push'], {'subscribed': False})
        self.assertEqual(self.subscriptions(), [])

    # --- account switch ---

    def test_account_switch_moves_the_token_to_the_new_user(self):
        self.sync(token='tok-a', user='owner')
        self.sync(token='tok-a', user='other')

        [sub] = self.subscriptions()
        self.assertEqual((sub.user_id, sub.tenant_id), (self.other.id, self.other.tenant_id))

    def test_account_switch_with_a_null_token_removes_the_previous_users_subscription(self):
        self.sync(token='tok-a', user='owner')
        self.sync(token=None, user='other')
        self.assertEqual(self.subscriptions(), [])

    def test_switch_after_anonymous_unlink_still_removes_the_previous_users_subscription(self):
        # A's expired-token sync nulls installation.user but (correctly) leaves
        # the subscription; B then signs in with notifications off. No owner
        # change is detectable at that point, yet A's row must go.
        self.sync(token='tok-a', user='owner')
        self.sync(token='tok-a', signed_in=False, user=None)
        self.assertIsNone(self.installation().user)
        self.assertEqual(len(self.subscriptions()), 1)

        self.sync(token=None, user='other')

        self.assertEqual(self.subscriptions(), [])

    # --- anonymous never removes ---

    def test_anonymous_signed_out_sync_leaves_the_subscription(self):
        self.sync(token='tok-a')
        response = self.sync(token=None, signed_in=False, user=None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['push'], {'subscribed': None})
        self.assertEqual(len(self.subscriptions()), 1)

    def test_expired_or_malformed_credentials_cannot_remove_the_subscription(self):
        self.sync(token='tok-a')
        for bad in ('Bearer not-a-jwt', 'Bearer eyJhbGciOiJIUzI1NiJ9.e30.bad'):
            self.seq += 1
            self.client.credentials(HTTP_AUTHORIZATION=bad)
            body = device_payload(
                installation_id=self.payload['installation_id'], sync_seq=self.seq, signed_in=False,
                push={'fcm_token': None, 'permission': 'denied'},
            )
            self.assertEqual(self.register(body).status_code, 200)
        self.assertEqual(len(self.subscriptions()), 1)

    def test_suspended_tenant_sync_cannot_remove_the_subscription(self):
        self.sync(token='tok-a')
        self.tenant.status = 'suspended'
        self.tenant.save(update_fields=['status'])

        self.sync(token=None, signed_in=False, user='owner')

        self.assertEqual(len(self.subscriptions()), 1)

    def test_stale_sync_seq_does_not_touch_the_subscription(self):
        self.sync(token='tok-a')
        self.authenticate(self.owner)
        body = device_payload(
            installation_id=self.payload['installation_id'], sync_seq=0,
            push={'fcm_token': None, 'permission': 'denied'},
        )
        response = self.register(body)

        self.assertEqual(response.data.get('ignored'), 'stale_sync_seq')
        self.assertEqual(len(self.subscriptions()), 1)

    # --- atomicity / isolation ---

    def test_a_failed_subscription_write_rolls_back_the_installation_update(self):
        self.sync(token='tok-a')
        before = self.installation().last_sync_seq

        with mock.patch(
            'apps.notifications.subscriptions.upsert_subscription', side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(RuntimeError):
                self.sync(token='tok-b')

        self.assertEqual(self.installation().last_sync_seq, before)
        self.assertEqual([s.fcm_token for s in self.subscriptions()], ['tok-a'])

    def test_other_tenant_cannot_see_the_reconciled_subscription(self):
        self.sync(token='tok-a')
        with tenant_context(self.other.tenant_id):
            self.assertEqual(PushSubscription.objects.count(), 0)
        with tenant_context(self.tenant.id):
            self.assertEqual(PushSubscription.objects.count(), 1)


class LogoutRemovesSubscriptionTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.create_owner(self.create_tenant())
        self.other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.payload = device_payload(push={'fcm_token': 'tok-a', 'permission': 'granted'})
        self.authenticate(self.owner)
        self.register(self.payload)

    def unlink(self):
        return self.client.delete(reverse('device-unlink-user', args=[self.payload['installation_id']]))

    def count(self):
        with tenant_context(None, is_super_admin=True):
            return PushSubscription.objects.count()

    def test_logout_removes_the_callers_subscription_and_is_idempotent(self):
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.unlink().status_code, 204)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.unlink().status_code, 204)

    def test_another_users_logout_does_not_remove_it(self):
        self.authenticate(self.other)
        self.assertEqual(self.unlink().status_code, 204)
        self.assertEqual(self.count(), 1)

    def test_unauthenticated_logout_is_rejected_and_keeps_it(self):
        self.client.credentials()
        self.assertEqual(self.unlink().status_code, 401)
        self.assertEqual(self.count(), 1)
