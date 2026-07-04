from .base import *

DEBUG = True
INSTALLED_APPS += ['debug_toolbar', 'django_extensions']
MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
INTERNAL_IPS = ['127.0.0.1']

# Auth emails (verification, OTP fallback, resets) print to the console in dev.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Module 14: run Celery tasks (notification emails) synchronously in dev/test
# so `manage.py test` and local runs don't need a separate worker process.
# prod.py does not set this — production requires the real `celery` worker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
