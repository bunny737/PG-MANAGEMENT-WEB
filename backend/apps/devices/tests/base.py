import copy
import secrets
import uuid

from django.core.cache import cache
from django.urls import reverse

from apps.accounts.tests.base import AuthAPITestCase
from apps.devices.models import AppVersionPolicy


def device_payload(**overrides):
    """A full, valid POST /devices/ body (all keys present)."""
    payload = {
        'installation_id': str(uuid.uuid4()),
        'sync_seq': 42,
        'signed_in': True,
        'platform': 'android',
        'flavor': 'prod',
        'build_mode': 'release',
        'app': {'version_name': '1.2.0', 'build_number': 12, 'package_id': 'com.pgmate.app'},
        'os': {'name': 'Android', 'version': '14', 'sdk_int': 34},
        'device': {'manufacturer': 'samsung', 'model': 'SM-S918B', 'is_physical': True},
        'screen': {'width_px': 1080, 'height_px': 2340, 'pixel_ratio': 2.6},
        'locale': 'te-IN',
        'utc_offset_minutes': 330,
        'timezone_abbr': 'IST',
        'push': {'fcm_token': None, 'permission': 'granted'},
        'network_type': 'wifi',
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return copy.deepcopy(payload)


def app_headers(platform='android', build=12, flavor='prod', version='1.2.0', installation_id=None):
    return {
        'HTTP_X_APP_PLATFORM': platform,
        'HTTP_X_APP_VERSION': version,
        'HTTP_X_APP_BUILD': str(build),
        'HTTP_X_APP_FLAVOR': flavor,
        'HTTP_X_INSTALLATION_ID': installation_id or str(uuid.uuid4()),
    }


class DevicesAPITestCase(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # policy cache + throttle counters
        # installation_id -> the app-generated secret, as the app keeps it:
        # register() makes one per install and sends it on every call.
        self.install_secrets = {}

    @staticmethod
    def create_policy(platform='android', flavor='prod', **overrides):
        values = {
            'min_build': 10, 'latest_build': 14, 'latest_version': '1.3.0',
            'store_url': 'https://play.google.com/store/apps/details?id=com.pgmate.app',
            'release_notes': {'en': 'Bug fixes', 'te': 'బగ్ పరిష్కారాలు'},
        }
        values.update(overrides)
        return AppVersionPolicy.objects.create(platform=platform, flavor=flavor, **values)

    def secret_for(self, installation_id):
        return self.install_secrets.setdefault(installation_id, secrets.token_urlsafe(32))

    def register(self, payload=None, **kwargs):
        """POST /devices/ like a current app build: sends the install's own
        generated secret unless the test passes HTTP_X_INSTALLATION_SECRET
        itself ('' = a build that predates secrets)."""
        payload = payload or device_payload()
        install = payload.get('installation_id')
        if 'HTTP_X_INSTALLATION_SECRET' not in kwargs and isinstance(install, str):
            kwargs['HTTP_X_INSTALLATION_SECRET'] = self.secret_for(install)
        return self.client.post(reverse('device-register'), payload, format='json', **kwargs)
