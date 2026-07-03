from .base import *

DEBUG = True
INSTALLED_APPS += ['debug_toolbar', 'django_extensions']
MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
INTERNAL_IPS = ['127.0.0.1']

# Auth emails (verification, OTP fallback, resets) print to the console in dev.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
