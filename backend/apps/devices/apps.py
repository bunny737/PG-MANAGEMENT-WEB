from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.devices'

    def ready(self):
        from . import policy  # noqa: F401  (connects the cache-invalidation signals)
