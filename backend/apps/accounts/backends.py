import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .normalization import normalize_email

logger = logging.getLogger(__name__)


class ActiveEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username if username is not None else kwargs.get(User.USERNAME_FIELD)
        if identifier is None or password is None:
            return None
        identifier = normalize_email(identifier) or identifier
        try:
            user = User.objects.get(email__iexact=identifier, is_active=True)
        except User.DoesNotExist:
            # Same dummy-hash trick Django's own ModelBackend uses: run a real
            # password hash on *something* so the unknown-user and
            # wrong-password paths cost the same, rather than a cheap
            # `check_password(..., None)` short-circuit.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Should be impossible under unique_active_email_lower; fail closed
            # and log loudly rather than guessing which row is right.
            logger.error('Multiple active users share email %r', identifier)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
