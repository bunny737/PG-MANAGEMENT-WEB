from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR.parent / '.env')

SECRET_KEY = env('SECRET_KEY', default='dev-secret-key-change-in-prod')
DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third party
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'drf_spectacular',
    'django_celery_beat',
    # local apps
    'apps.core',
    'apps.accounts',
    'apps.properties',
    'apps.residents',
    'apps.billing',
    'apps.operations',
    'apps.subscriptions',
    'apps.notifications',
    'apps.audit',
    'apps.reporting',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Clears the Postgres tenant GUCs after each request (set by
    # apps.core.authentication.TenantJWTAuthentication during DRF auth).
    'apps.core.middleware.TenantContextMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
AUTH_USER_MODEL = 'accounts.User'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', default='pg_platform'),
        'USER': env('DB_USER', default='postgres'),
        'PASSWORD': env('DB_PASSWORD', default='postgres'),
        'HOST': env('DB_HOST', default='db'),
        'PORT': env('DB_PORT', default='5432'),
    }
}

# i18n — architecture mandatory from day one.
# MVP: English + Telugu active (owner decision 2026-08-11 — Telugu pulled
# forward from V2). V2: Hindi. V3: Tamil + Malayalam.
USE_I18N = True
USE_L10N = True
LANGUAGE_CODE = 'en'
LANGUAGES = [
    ('en', 'English'),
    ('hi', 'Hindi'),
    ('te', 'Telugu'),
    ('ta', 'Tamil'),
    ('ml', 'Malayalam'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # Enforces tenant suspension + sets the RLS tenant context per request.
        'apps.core.authentication.TenantJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Adds a machine-readable `code` field the frontend switches on.
    'EXCEPTION_HANDLER': 'apps.core.exceptions.api_exception_handler',
    # Rate limiting on auth endpoints (PRD Module 1 security requirement).
    'DEFAULT_THROTTLE_RATES': {
        'signup': '10/hour',
        'login': '10/min',
        'verify_email': '10/min',
        'resend_verification': '5/min',
        'otp_request': '3/min',
        'otp_verify': '10/min',
        'password_reset': '5/min',
    },
}

# Shared cache. DRF throttle state (auth rate limiting — PRD Module 1 security
# requirement) MUST be shared across gunicorn workers / pods, so it cannot live
# in the per-process LocMemCache. Redis is already a hard dependency (Celery).
# dev.py overrides this with LocMemCache so `manage.py test` needs no Redis.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': env('REDIS_CACHE_URL', default=env('REDIS_URL', default='redis://redis:6379/1')),
        'KEY_PREFIX': 'pgmgmt',
    }
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'PG/Hostel Management API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # users.language_code and tenants.default_language share one choice set.
    'ENUM_NAME_OVERRIDES': {'LanguageEnum': LANGUAGES},
}

# PRD §11: bcrypt password hashing.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Auth flow settings (technical tuning — plan limits live in PlatformConfig).
FRONTEND_BASE_URL = env('FRONTEND_BASE_URL', default='http://localhost:3000')
EMAIL_VERIFICATION_TTL_SECONDS = 60 * 60 * 72  # 3 days
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5

# Email
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@localhost')

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}

# Celery
CELERY_BROKER_URL = env('REDIS_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = env('REDIS_URL', default='redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
# Module 14 V2: recurring notification sweeps (trial reminders, etc.) are
# django-celery-beat PeriodicTask rows — DB-editable cadence, no code
# deploy to change "run daily at 9am" to "run at 6am". The scheduler itself
# runs as a separate `celery-beat` process (docker-compose.yml); this
# setting only names which scheduler class `manage.py` management commands
# and the beat process use to read schedules from the DB.
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Firebase Cloud Messaging (Module 14 V2 push channel — web push via the
# frontend's Serwist service worker, and native Android/iOS later). Blank in
# dev/test: apps.notifications.channels.push falls back to logging
# status=skipped, same fail-open discipline as every other channel. Prefer
# FIREBASE_CREDENTIALS_PATH (a mounted service-account JSON file) in
# production; FIREBASE_CREDENTIALS_JSON (the raw JSON as an env var) is the
# simpler option for platforms without file mounts.
FIREBASE_CREDENTIALS_PATH = env('FIREBASE_CREDENTIALS_PATH', default='')
FIREBASE_CREDENTIALS_JSON = env('FIREBASE_CREDENTIALS_JSON', default='')

# Razorpay (locked stack — platform subscription billing ONLY, never resident
# rent). Blank in dev/test falls back to a local stub client (see
# apps.subscriptions.razorpay_client) so this environment doesn't need real
# Razorpay credentials; fill in .env to activate real billing.
RAZORPAY_KEY_ID = env('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET = env('RAZORPAY_KEY_SECRET', default='')
RAZORPAY_WEBHOOK_SECRET = env('RAZORPAY_WEBHOOK_SECRET', default='')
# The Razorpay webhook endpoint is public and unauthenticated (trust comes from
# the HMAC signature). If no webhook secret is configured, signature checks are
# skipped — that is a dev/test convenience ONLY and MUST NOT hold in production,
# where an unverified payload could drive tenant status and platform payments.
# dev.py flips this to True; base (prod) fails closed.
RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS = env.bool('RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS', default=False)

# Storage
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# AWS S3 (locked stack — resident ID document uploads etc.). Falls back to
# local filesystem storage when no bucket is configured (dev/test), so this
# environment doesn't need real AWS credentials; fill in .env to activate.
AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME', default='')
if AWS_STORAGE_BUCKET_NAME:
    AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID', default='')
    AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY', default='')
    AWS_S3_REGION_NAME = env('AWS_S3_REGION_NAME', default='ap-south-1')
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    STORAGES = {
        'default': {'BACKEND': 'storages.backends.s3.S3Storage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
