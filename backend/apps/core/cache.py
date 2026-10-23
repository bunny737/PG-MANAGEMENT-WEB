"""Redis cache that fails open (prod).

The cache only holds DRF throttle counters and the app-version policy, and
Redis runs on a single worker VM. If Redis is down, a cache miss is the right
answer: no rate limiting for a while beats 500s on every login.
"""
import logging

from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class FailOpenRedisCache(RedisCache):
    def _fail_open(self, operation, default):
        logger.warning('Redis cache unavailable during %s; failing open', operation, exc_info=True)
        return default

    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default, version)
        except RedisError:
            return self._fail_open('get', default)

    def get_many(self, keys, version=None):
        try:
            return super().get_many(keys, version)
        except RedisError:
            return self._fail_open('get_many', {})

    def set(self, key, value, timeout=None, version=None):
        try:
            return super().set(key, value, timeout, version)
        except RedisError:
            return self._fail_open('set', None)

    def set_many(self, data, timeout=None, version=None):
        try:
            return super().set_many(data, timeout, version)
        except RedisError:
            return self._fail_open('set_many', list(data))

    def add(self, key, value, timeout=None, version=None):
        try:
            return super().add(key, value, timeout, version)
        except RedisError:
            return self._fail_open('add', False)

    def delete(self, key, version=None):
        try:
            return super().delete(key, version)
        except RedisError:
            return self._fail_open('delete', False)

    def has_key(self, key, version=None):
        try:
            return super().has_key(key, version)
        except RedisError:
            return self._fail_open('has_key', False)
