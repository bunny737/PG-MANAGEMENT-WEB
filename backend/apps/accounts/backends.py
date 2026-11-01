import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .normalization import normalize_email

logger = logging.getLogger(__name__)


class ActiveEmailBackend(ModelBackend):
    """Password authentication for the STAFF pool (Super Admin, Owner, Manager, Receptionist).

    This is the only entry in AUTHENTICATION_BACKENDS, so Django admin and the staff
    `/auth/login/` keep working unchanged and can never reach a resident account that happens
    to share an email. Residents authenticate through ResidentEmailBackend, which is
    deliberately NOT registered in settings: only the resident login serializer calls it, so no
    generic `authenticate()` call can ever resolve to the resident pool (Module 26)."""

    pool = 'staff_pool'

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username if username is not None else kwargs.get(User.USERNAME_FIELD)
        if identifier is None or password is None:
            return None
        identifier = normalize_email(identifier) or identifier
        try:
            user = getattr(User.objects, self.pool)().get(email__iexact=identifier, is_active=True)
        except User.DoesNotExist:
            # Same dummy-hash trick Django's own ModelBackend uses: run a real
            # password hash on *something* so the unknown-user and
            # wrong-password paths cost the same, rather than a cheap
            # `check_password(..., None)` short-circuit.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Should be impossible under the per-pool unique indexes; fail closed
            # and log loudly rather than guessing which row is right.
            logger.error('Multiple active users in %s share email %r', self.pool, identifier)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


class ResidentEmailBackend(ActiveEmailBackend):
    """Password authentication for the RESIDENT pool. Not registered in settings; see above."""

    pool = 'resident_pool'
