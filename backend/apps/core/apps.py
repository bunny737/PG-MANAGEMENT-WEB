from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'

    def ready(self):
        from . import checks, schema  # noqa: F401 — schema registers the spectacular auth extension; checks the deploy checks
