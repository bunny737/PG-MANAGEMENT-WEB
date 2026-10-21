"""Gunicorn settings for Cloud Run (docs/deployment.md).

2 workers x 4 threads = 8 concurrent requests per instance, matching the
Cloud Run service's --concurrency 8 — Cloud Run must never queue more work on
an instance than gunicorn can run, or it scales out too late. The worker
timeout stays below Cloud Run's 60 s request timeout so gunicorn, not the
platform, ends a stuck request (and logs it).

Gunicorn is required, not incidental: it exposes RAW_URI, which BFF origin
signatures are verified against (apps.core.net), and /health/ready/ reports
503 on any server that doesn't.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = 'gthread'
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
threads = int(os.environ.get('GUNICORN_THREADS', '4'))
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '50'))
graceful_timeout = 25
keepalive = 5
# Cloud Run already logs every request; gunicorn's access log would double it.
accesslog = None
errorlog = '-'
loglevel = 'info'
# Restart workers periodically to contain slow leaks (WeasyPrint, Pillow).
max_requests = 1000
max_requests_jitter = 100
