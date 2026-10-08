import uuid

from django.urls import reverse

from apps.devices.models import AppInstallation

from .base import DevicesAPITestCase, device_payload


class DeviceUnlinkTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.create_owner(self.create_tenant())
        self.other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.payload = device_payload()
        self.authenticate(self.owner)
        self.register(self.payload)

    def unlink(self, installation_id=None):
        return self.client.delete(reverse('device-unlink-user', args=[installation_id or self.payload['installation_id']]))

    def test_owner_unlinks_and_gets_204(self):
        self.assertEqual(self.unlink().status_code, 204)
        self.assertIsNone(AppInstallation.objects.get().user)

    def test_is_idempotent(self):
        self.unlink()
        self.assertEqual(self.unlink().status_code, 204)

    def test_non_owner_gets_204_and_the_link_survives(self):
        self.authenticate(self.other)
        self.assertEqual(self.unlink().status_code, 204)
        self.assertEqual(AppInstallation.objects.get().user, self.owner)

    def test_unknown_installation_gets_204(self):
        self.assertEqual(self.unlink(str(uuid.uuid4())).status_code, 204)

    def test_requires_authentication(self):
        self.client.credentials()
        self.assertEqual(self.unlink().status_code, 401)
        self.assertEqual(AppInstallation.objects.get().user, self.owner)
