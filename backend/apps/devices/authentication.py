from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError

from apps.core.authentication import TenantJWTAuthentication


class OptionalTenantJWTAuthentication(TenantJWTAuthentication):
    """A valid bearer token authenticates; a missing, expired, malformed or
    otherwise rejected one (including a suspended tenant) means anonymous —
    never 401. For endpoints the app calls without refreshing tokens first."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except (AuthenticationFailed, TokenError):
            return None
