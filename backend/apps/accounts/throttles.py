import hashlib
from collections.abc import Mapping

from rest_framework.exceptions import ParseError

from apps.core.throttles import SimpleRateThrottle

from .normalization import normalize_email


class OtpEmailThrottle(SimpleRateThrottle):
    """Per requested email on the email-code request endpoint, so rotating IPs
    cannot flood one inbox (the per-IP ScopedRateThrottle runs alongside).
    Keyed on a digest — the cache never holds the address. Without a usable
    email there is nothing to key on; validation rejects the request anyway."""

    scope = 'otp_email_request_email'

    def get_cache_key(self, request, view):
        try:
            data = request.data
        except ParseError:
            return None
        if not isinstance(data, Mapping):
            return None
        email = data.get('email')
        if not isinstance(email, str):
            return None
        normalized = normalize_email(email)
        if not normalized:
            return None
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': digest}
