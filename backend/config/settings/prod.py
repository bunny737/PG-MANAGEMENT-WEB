"""Production settings (Cloud Run + Cloud SQL + GCS behind Google's external
HTTPS load balancer). See docs/deployment.md."""
from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

# Refuse to boot with the dev default or a short key, and require a dedicated
# JWT key so SECRET_KEY can rotate (via SECRET_KEY_FALLBACKS) without logging
# everyone out.
if SECRET_KEY == 'dev-secret-key-change-in-prod' or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('SECRET_KEY must be set to a random value of at least 50 characters.')
if len(JWT_SIGNING_KEY) < 50:
    raise ImproperlyConfigured('JWT_SIGNING_KEY must be set to a random value of at least 50 characters.')
SECRET_KEY_FALLBACKS = env.list('SECRET_KEY_FALLBACKS', default=[])

# The load balancer terminates TLS and Cloud Run forwards X-Forwarded-Proto.
# Without this, SECURE_SSL_REDIRECT sees plain HTTP and redirects forever.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS is owned by the load balancer (a custom response header on every
# backend service), so all three hosts send exactly one, consistent header.
# Set SECURE_HSTS_SECONDS only if Django is ever served without that LB.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
if not SECURE_HSTS_SECONDS:
    SILENCED_SYSTEM_CHECKS = ['security.W004']

# Trusted client IP: the LB overwrites this header on every backend.
CLIENT_IP_HEADER = env('CLIENT_IP_HEADER', default='X-PGLive-Client-IP')
REQUIRE_RAW_URI = True
IAP_REQUIRED = env.bool('IAP_REQUIRED', default=True)

# Database: short-lived persistent connections. RLS uses session-level GUCs,
# which TenantContextMiddleware clears after every request, so reuse is safe;
# never put a transaction-mode pooler in front of this database.
DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=60)
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
if not str(DATABASES['default']['HOST']).startswith('/'):
    # TCP connections must be encrypted. The /cloudsql unix socket is already
    # an encrypted, IAM-authorised Cloud SQL connector tunnel.
    DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = env('DB_SSLMODE', default='require')

# Static files (Django admin) served by WhiteNoise from the container.
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
                  'whitenoise.middleware.WhiteNoiseMiddleware')
STORAGES['staticfiles'] = {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}

# Redis (on the worker VM) must never hang a request: short timeouts, and the
# throttle cache fails open (a Redis outage means no rate limiting rather than
# 500s on login). Celery publishing gets bounded retries.
CACHES['default']['BACKEND'] = 'apps.core.cache.FailOpenRedisCache'
CACHES['default']['OPTIONS'] = {'socket_connect_timeout': 2, 'socket_timeout': 2}
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_TRANSPORT_OPTIONS = {'socket_connect_timeout': 3, 'socket_timeout': 5}
CELERY_TASK_PUBLISH_RETRY_POLICY = {'max_retries': 2, 'interval_start': 0, 'interval_step': 0.5, 'interval_max': 1}

# Structured logs for Cloud Logging (apps.core.log_format scrubs PII).
LOGGING['formatters']['json'] = {'()': 'apps.core.log_format.CloudLoggingFormatter'}
LOGGING['handlers']['app_console']['formatter'] = 'json'
LOGGING['loggers']['apps'] = {'handlers': ['app_console'], 'level': 'INFO', 'propagate': False}
LOGGING['root'] = {'handlers': ['app_console'], 'level': 'WARNING'}

SENTRY_DSN = env('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env('SENTRY_ENVIRONMENT', default='production'),
        release=env('APP_RELEASE', default=None),
        traces_sample_rate=env.float('SENTRY_TRACES_SAMPLE_RATE', default=0.0),
        send_default_pii=False,
    )
