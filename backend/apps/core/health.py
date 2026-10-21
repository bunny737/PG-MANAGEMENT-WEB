"""Unauthenticated probes for Cloud Run and uptime checks. Tenant-free: no
RLS context is set and nothing tenant-scoped is read.

/health/        liveness — the process is serving; no dependencies touched.
/health/ready/  readiness — the database answers, and (prod) the WSGI server
                exposes RAW_URI, without which BFF origin signatures can't be
                verified (apps.core.net) — so a non-gunicorn server never
                reports ready.
"""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def liveness(request):
    return JsonResponse({'status': 'ok'})


def _database_ok():
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return True
    except Exception:
        return False


@never_cache
@require_GET
def readiness(request):
    checks = {'database': 'ok' if _database_ok() else 'error'}
    if getattr(settings, 'REQUIRE_RAW_URI', False):
        checks['raw_uri'] = 'ok' if 'RAW_URI' in request.META else 'missing'
    healthy = all(value == 'ok' for value in checks.values())
    return JsonResponse({'status': 'ok' if healthy else 'error', 'checks': checks},
                        status=200 if healthy else 503)
