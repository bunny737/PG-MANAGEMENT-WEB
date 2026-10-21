"""Queueing non-critical Celery tasks from a request.

Redis (the broker) runs on a single worker VM. When it is unreachable, a
notification email must not turn an already-committed request into a 500, so
broker errors are logged (and alerted on) instead of raised. Only use this
for tasks whose loss is acceptable or that a scheduled sweep retries.
"""
import logging

from kombu.exceptions import OperationalError
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def enqueue(task, *args, **kwargs):
    try:
        return task.delay(*args, **kwargs)
    except (OperationalError, RedisError):
        logger.error('Could not queue task %s: broker unavailable', task.name, exc_info=True)
        return None
