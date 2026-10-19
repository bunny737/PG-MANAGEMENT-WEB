import hashlib
from collections.abc import Mapping

from rest_framework.exceptions import ParseError
from rest_framework.throttling import SimpleRateThrottle


class ContactIPThrottle(SimpleRateThrottle):
    """Best-effort per-client-IP limit on the public contact form. Behind a proxy
    the IP is only as trustworthy as the proxy setup (see module 01 spec, [OPEN])."""

    scope = 'contact_message'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class ContactEmailThrottle(SimpleRateThrottle):
    """Per sender email, so rotating IPs does not lift the limit. Without a usable
    email there is nothing to key on (validation rejects the request anyway)."""

    scope = 'contact_message_email'

    def get_cache_key(self, request, view):
        try:
            data = request.data
        except ParseError:
            return None
        if not isinstance(data, Mapping):
            return None
        email = data.get('email')
        if not isinstance(email, str) or not email.strip():
            return None
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': digest}
