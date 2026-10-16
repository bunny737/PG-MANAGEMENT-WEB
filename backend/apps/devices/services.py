import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AppInstallation, AppInstallationHistory

logger = logging.getLogger(__name__)

INVALID_SECRET = 'invalid_installation_secret'
UNCLAIMED_INSTALL = 'unclaimed_install'

# Possession outcomes for an existing install.
_OK, _REJECT, _IGNORE = 'ok', 'reject', 'ignore'


@dataclass
class RegistrationResult:
    installation: Optional[AppInstallation]
    created: bool = False
    ignored: Optional[str] = None
    # True/False once an authenticated sync reconciled the push subscription;
    # None when it wasn't evaluated (anonymous sync, stale sync_seq).
    push_subscribed: Optional[bool] = None
    # INVALID_SECRET when the call could not prove possession of the install.
    rejected: Optional[str] = None


def _hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def _is_stakeholder(installation, user):
    """Who may use (and claim) an install that has no secret yet: its linked
    user, or the owner of a push subscription on it. An install with neither
    is open (nothing to take over). Otherwise anyone who learned the UUID
    could relink it and drop the real owner's subscription."""
    from apps.core.tenancy import tenant_context
    from apps.notifications.models import PushSubscription

    with tenant_context(is_super_admin=True):
        owners = set(PushSubscription.objects.filter(installation=installation).values_list('user_id', flat=True))
    if installation.user_id is None and not owners:
        return True
    return user is not None and (installation.user_id == user.id or user.id in owners)


def _check_possession(installation, secret, user):
    """The app generates its install secret itself and sends it on every
    call (X-Installation-Secret); the server only ever stores its hash.

    - Install has a secret → the call must present it (else _REJECT).
    - Install has none yet (registered by a build that predates secrets) →
      only a stakeholder is served. A stakeholder sending a secret claims the
      install with it. A non-stakeholder is ignored when anonymous (e.g. the
      owner's session just expired: no state change, the next signed-in
      sync claims it) and rejected when authenticated (someone else is
      signed in on this phone: the app must start a new install).

    Returns (outcome, proved): `proved` is true when the call showed the
    install's secret (matched, or just claimed with it) — i.e. it comes
    from the device itself."""
    if installation.secret_hash:
        ok = bool(secret) and hmac.compare_digest(installation.secret_hash, _hash_secret(secret))
        return (_OK, True) if ok else (_REJECT, False)
    if not _is_stakeholder(installation, user):
        return (_IGNORE if user is None else _REJECT), False
    if secret:
        installation.secret_hash = _hash_secret(secret)
        AppInstallation.objects.filter(pk=installation.pk).update(secret_hash=installation.secret_hash)
        return _OK, True
    return _OK, False


def register_installation(*, installation_id, sync_seq, signed_in, fields, user, secret=None):
    """Upsert one install. `user` is the authenticated user or None (anonymous).
    `secret` is the app-generated X-Installation-Secret header (None if the
    build predates secrets).

    - Possession (`_check_possession`): installation_id alone is not a
      credential. A new install stores the hash of the secret it was created
      with; a later call without it is rejected (`rejected=INVALID_SECRET`),
      or ignored (`ignored=UNCLAIMED_INSTALL`) for an anonymous outsider on
      a secret-less install.
    - Stale `sync_seq` (< stored) is ignored wholesale; equal is reprocessed.
    - Authenticated: link to `user` (last writer wins). Anonymous with
      signed_in=False: unlink. Anonymous with signed_in=True: leave as is.
    - A FCM token belongs to one install: it is nulled on any other holder.
    - A history row is written on first sighting and whenever the build or
      OS version changes.
    - Authenticated syncs also reconcile the push subscription (see
      `_reconcile_push_subscription`), on create and update alike.
    """
    with transaction.atomic():
        installation = (
            AppInstallation.objects.select_for_update().filter(installation_id=installation_id).first()
        )
        created = installation is None
        now = timezone.now()
        proved = created and bool(secret)
        if created:
            try:
                with transaction.atomic():
                    installation = AppInstallation.objects.create(
                        installation_id=installation_id, user=user, last_sync_seq=sync_seq,
                        first_seen_at=now, last_seen_at=now,
                        secret_hash=_hash_secret(secret) if secret else '',
                        **{**fields, 'fcm_token': None},
                    )
            except IntegrityError:
                # Lost a create race on installation_id: treat as an update,
                # which must then prove possession like any other.
                installation = AppInstallation.objects.select_for_update().get(installation_id=installation_id)
                created = False
            else:
                _record_history(installation, now)

        if not created:
            outcome, proved = _check_possession(installation, secret, user)
            if outcome == _REJECT:
                logger.warning('rejected device sync without a valid installation secret installation_id=%s',
                               installation_id)
                return RegistrationResult(installation=None, rejected=INVALID_SECRET)
            if outcome == _IGNORE:
                logger.info('ignored anonymous sync for an unclaimed install installation_id=%s', installation_id)
                return RegistrationResult(installation=None, ignored=UNCLAIMED_INSTALL)
            if sync_seq < installation.last_sync_seq:
                logger.info(
                    'ignored stale device sync installation_id=%s sync_seq=%s last_sync_seq=%s',
                    installation_id, sync_seq, installation.last_sync_seq,
                )
                return RegistrationResult(installation=installation, ignored='stale_sync_seq')

        token = fields.get('fcm_token')
        if token:
            AppInstallation.objects.filter(fcm_token=token).exclude(installation_id=installation_id).update(
                fcm_token=None
            )
            if created:
                installation.fcm_token = token
                installation.save(update_fields=['fcm_token'])

        if not created:
            changed = (
                installation.build_number != fields['build_number']
                or installation.os_version != fields['os_version']
            )
            for name, value in fields.items():
                setattr(installation, name, value)
            installation.last_sync_seq = sync_seq
            installation.last_seen_at = now
            if user is not None:
                installation.user = user
            elif not signed_in:
                installation.user = None
            installation.save()
            if changed:
                _record_history(installation, now)

        push_subscribed = _reconcile_push_subscription(
            installation=installation, user=user, token=token, signed_in=signed_in, proved=proved,
        )
        return RegistrationResult(installation=installation, created=created, push_subscribed=push_subscribed)


def _reconcile_push_subscription(*, installation, user, token, signed_in, proved):
    """Keeps notifications.PushSubscription — the one record push delivery
    reads — in step with what the device just reported, so the app needs no
    second registration call.

    Anonymous syncs only ever remove, and only when they prove possession of
    the install (its secret) and report `signed_in: false`: that is the
    device itself after a forced/offline logout, so it must stop receiving
    the previous user's pushes. Without the secret an anonymous call proves
    nothing (OptionalTenantJWTAuthentication treats expired/forged tokens as
    anonymous), so it leaves subscriptions alone."""
    from apps.notifications import subscriptions

    if user is None:
        if not signed_in and proved:
            subscriptions.remove_all_for_installation(installation=installation)
            return False
        return None
    if user.tenant_id is None:
        return None
    subscriptions.remove_foreign_for_installation(installation=installation, keep_user=user)
    if token:
        subscriptions.upsert_subscription(
            user=user, token=token, device_type=installation.platform, installation=installation,
        )
        return True
    subscriptions.remove_for_installation(installation=installation, user=user)
    return False


def _record_history(installation, now):
    AppInstallationHistory.objects.create(
        installation=installation, build_number=installation.build_number,
        version_name=installation.version_name, os_version=installation.os_version, recorded_at=now,
    )


def unlink_user(*, installation_id, user, sync_seq=None, secret=None):
    """Logout: remove `user`'s push subscription on this install and clear
    the user link if it is `user`'s. Silent otherwise.

    `sync_seq` (the app's next device-sync counter value) makes logout take
    part in the same ordering as POST /devices/: it is stored as
    `last_sync_seq`, so an authenticated registration that was already in
    flight (lower seq) is ignored as stale instead of re-subscribing a
    logged-out device. Only a caller with a stake in the install can advance
    it — otherwise anyone could push it out of reach and freeze the device's
    syncs: its linked user, the owner of a subscription on it, or a caller
    presenting the install's secret (the device itself, e.g. after a
    signed-out sync already removed everything)."""
    from apps.notifications import subscriptions

    with transaction.atomic():
        installation = (
            AppInstallation.objects.select_for_update().filter(installation_id=installation_id).first()
        )
        if installation is None:
            return
        removed = subscriptions.remove_for_installation(installation=installation, user=user)
        is_linked_user = installation.user_id == user.id
        proved = bool(secret and installation.secret_hash) and hmac.compare_digest(
            installation.secret_hash, _hash_secret(secret),
        )
        if not (is_linked_user or removed or proved):
            return
        update_fields = []
        if is_linked_user:
            installation.user = None
            update_fields.append('user')
        if sync_seq is not None and sync_seq > installation.last_sync_seq:
            installation.last_sync_seq = sync_seq
            update_fields.append('last_sync_seq')
        if update_fields:
            installation.save(update_fields=update_fields)
