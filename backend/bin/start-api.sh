#!/bin/sh
# API container entrypoint. Refuses to start on a deploy-time configuration error (blank or placeholder
# Razorpay keys, an http FRONTEND_BASE_URL, ...) instead of serving with a broken setup: the Cloud Run
# revision then never becomes ready, so infra/deploy.sh aborts before any traffic moves. Warnings do not
# block (--fail-level ERROR). Jobs, the Celery worker and beat override the command and don't run this.
set -e
python manage.py check --deploy --fail-level ERROR
exec gunicorn config.wsgi:application --config gunicorn.conf.py
