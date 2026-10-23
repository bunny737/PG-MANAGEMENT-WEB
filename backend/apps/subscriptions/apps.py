from django.apps import AppConfig

class SubscriptionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.subscriptions'

    def ready(self):
        from . import checks, signals  # noqa: F401 — signals: Bed post_save/post_delete receivers; checks: the Razorpay deploy check
