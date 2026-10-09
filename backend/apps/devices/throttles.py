import uuid
from collections.abc import Mapping

from rest_framework.exceptions import ParseError
from rest_framework.throttling import SimpleRateThrottle


class DeviceRegisterIPThrottle(SimpleRateThrottle):
    scope = 'device_register_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class DeviceRegisterInstallationThrottle(SimpleRateThrottle):
    """Per installation_id from the body. Without a parseable UUID there is
    nothing to key on (validation will reject the request anyway)."""

    scope = 'device_register_installation'

    def get_cache_key(self, request, view):
        try:
            data = request.data
        except ParseError:
            return None
        if not isinstance(data, Mapping):
            return None
        try:
            ident = str(uuid.UUID(str(data.get('installation_id'))))
        except ValueError:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': ident}
