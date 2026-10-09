from rest_framework import serializers

from .models import Flavor, Platform

MAX_STR = 64


class AppInfoSerializer(serializers.Serializer):
    version_name = serializers.CharField(max_length=MAX_STR, allow_blank=True)
    build_number = serializers.IntegerField(min_value=1, max_value=2**31 - 1)
    package_id = serializers.CharField(max_length=128, allow_blank=True)


class OsInfoSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_STR, allow_blank=True)
    version = serializers.CharField(max_length=MAX_STR, allow_blank=True)
    sdk_int = serializers.IntegerField(min_value=0, max_value=10_000, allow_null=True, required=False)


class DeviceInfoSerializer(serializers.Serializer):
    manufacturer = serializers.CharField(max_length=MAX_STR, allow_blank=True)
    model = serializers.CharField(max_length=MAX_STR, allow_blank=True)
    is_physical = serializers.BooleanField()


class ScreenInfoSerializer(serializers.Serializer):
    width_px = serializers.IntegerField(min_value=0, max_value=100_000)
    height_px = serializers.IntegerField(min_value=0, max_value=100_000)
    pixel_ratio = serializers.FloatField(min_value=0, max_value=100)


class PushInfoSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(max_length=255, allow_null=True, allow_blank=True, required=False)
    permission = serializers.CharField(max_length=32, allow_blank=True)


class DeviceRegistrationSerializer(serializers.Serializer):
    """Body of POST /devices/. Unknown keys are ignored (DRF default)."""

    installation_id = serializers.UUIDField()
    sync_seq = serializers.IntegerField(min_value=0, max_value=2**53)
    signed_in = serializers.BooleanField()
    platform = serializers.ChoiceField(choices=Platform.choices)
    flavor = serializers.ChoiceField(choices=Flavor.choices)
    build_mode = serializers.CharField(max_length=16, allow_blank=True)
    app = AppInfoSerializer()
    os = OsInfoSerializer()
    device = DeviceInfoSerializer()
    screen = ScreenInfoSerializer()
    locale = serializers.CharField(max_length=16, allow_blank=True)
    utc_offset_minutes = serializers.IntegerField(min_value=-1440, max_value=1440)
    timezone_abbr = serializers.CharField(max_length=16, allow_blank=True)
    push = PushInfoSerializer()
    network_type = serializers.CharField(max_length=32, allow_null=True, allow_blank=True, required=False)

    def to_installation_fields(self):
        """Flatten validated_data into AppInstallation column values."""
        d = self.validated_data
        return {
            'platform': d['platform'],
            'flavor': d['flavor'],
            'build_mode': d['build_mode'],
            'version_name': d['app']['version_name'],
            'build_number': d['app']['build_number'],
            'package_id': d['app']['package_id'],
            'os_name': d['os']['name'],
            'os_version': d['os']['version'],
            'os_sdk_int': d['os'].get('sdk_int'),
            'device_manufacturer': d['device']['manufacturer'],
            'device_model': d['device']['model'],
            'is_physical': d['device']['is_physical'],
            'screen_width_px': d['screen']['width_px'],
            'screen_height_px': d['screen']['height_px'],
            'pixel_ratio': d['screen']['pixel_ratio'],
            'locale': d['locale'],
            'utc_offset_minutes': d['utc_offset_minutes'],
            'timezone_abbr': d['timezone_abbr'],
            'network_type': d.get('network_type') or '',
            'push_permission': d['push']['permission'],
            # Blank is "no token". The body always carries the full device
            # state, so an absent token clears a stale stored one.
            'fcm_token': d['push'].get('fcm_token') or None,
        }


class VersionPolicyQuerySerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=Platform.choices)
    build = serializers.IntegerField(min_value=0, max_value=2**31 - 1)
    version = serializers.CharField(max_length=MAX_STR, required=False, allow_blank=True)
    flavor = serializers.ChoiceField(choices=Flavor.choices, default=Flavor.PROD)
