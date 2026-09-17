from django.apps import AppConfig

class SubscriptionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.subscriptions'

    def ready(self):
        from . import signals  # noqa: F401 — registers Bed post_save/post_delete receivers
