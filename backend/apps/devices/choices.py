"""Enums with no model imports, so apps.devices.client can be loaded by the
logging config before the app registry is ready."""
from django.db import models
from django.utils.translation import gettext_lazy as _

DEFAULT_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


class Platform(models.TextChoices):
    ANDROID = 'android', _('Android')
    IOS = 'ios', _('iOS')


class Flavor(models.TextChoices):
    DEV = 'dev', _('Dev')
    PROD = 'prod', _('Prod')
