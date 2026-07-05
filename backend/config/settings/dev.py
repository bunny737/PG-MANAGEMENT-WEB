from .base import *

DEBUG = True
INSTALLED_APPS += ['debug_toolbar', 'django_extensions', 'corsheaders']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware'] + MIDDLEWARE
MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
INTERNAL_IPS = ['127.0.0.1']

# Dev-only: the Next.js dev server calls Django directly from the browser
# (no BFF proxy yet — see docs/frontend-plan.md §3.1, still to be built).
# Not needed in prod, where the proxy makes API calls same-origin.
CORS_ALLOWED_ORIGINS = ['http://localhost:3000']

# Auth emails (verification, OTP fallback, resets) print to the console in dev.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Module 14: run Celery tasks (notification emails) synchronously in dev/test
# so `manage.py test` and local runs don't need a separate worker process.
# prod.py does not set this — production requires the real `celery` worker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
