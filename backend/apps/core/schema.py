"""drf-spectacular extensions. Imported from CoreConfig.ready() so the
extension registers before schema generation."""
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class TenantJWTAuthenticationScheme(SimpleJWTScheme):
    target_class = 'apps.core.authentication.TenantJWTAuthentication'
