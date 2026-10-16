import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AppInstallation, AppInstallationHistory

logger = logging.getLogger(__name__)

INVALID_SECRET = 'invalid_installation_secret'


@dataclass
class RegistrationResult:
    installation: Optional[AppInstallation]
    created: bool = False
    ignored: Optional[str] = None
    # True/False once an authenticated sync reconciled the push subscription;
    # None when it wasn't evaluated (anonymous sync, stale sync_seq).
    push_subscribed: Optional[bool] = None
    # Set when this call minted the install's secret (first registration, or
    # claiming a legacy install). Returned to the app exactly once.
    issued_secret: Optional[str] = None
    # INVALID_SECRET when the call could not prove possession of the install.
    rejected: Optional[str] = None


def _hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def _new_secret():
    return secrets.token_urlsafe(32)


def _may_claim_legacy(installation, user):
    """A legacy install (no secret yet) may only be claimed by someone with
    a stake in it: its linked user, or the owner of a push subscription on
    it. An install with neither is up for grabs (nothing to take over).
    Otherwise anyone who learned the UUID could claim it and, in the same
    call, relink it and drop the real owner's subscription."""
    from apps.core.tenancy import tenant_context
    from apps.notifications.models import PushSubscription

    with tenant_context(is_super_admin=True):
        owners = set(PushSubscription.objects.filter(installation=installation).values_list('user_id', flat=True))
    if installation.user_id is None and not owners:
        return True
    return user is not None and (installation.user_id == user.id or user.id in owners)


def _verify_or_claim(installation, secret, user):
    """Returns (ok, issued_secret). A claimed install must present its
    secret; a legacy install with no secret yet is claimed by this call if
    `_may_claim_legacy` allows it."""
    if installation.secret_hash:
        ok = bool(secret) and hmac.compare_digest(installation.secret_hash, _hash_secret(secret))
        return ok, None
    if not _may_claim_legacy(installation, user):
        return False, None
    issued = _new_secret()
    installation.secret_hash = _hash_secret(issued)
    AppInstallation.objects.filter(pk=installation.pk).update(secret_hash=installation.secret_hash)
    return True, issued


def register_installation(*, installation_id, sync_seq, signed_in, fields, user, secret=None):
    """Upsert one install. `user` is the authenticated user or None (anonymous).
    `secret` is the X-Installation-Secret header (None if absent).

    - Possession: an existing install must present its secret, or the whole
      call is rejected (`rejected=INVALID_SECRET`) — the installation_id
      alone is not a credential. A new install gets a secret minted here;
      a legacy install with none is claimed by its next call.
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
        issued_secret = None
        created = installation is None
        now = timezone.now()
        if created:
            issued_secret = _new_secret()
            try:
                with transaction.atomic():
                    installation = AppInstallation.objects.create(
                        installation_id=installation_id, user=user, last_sync_seq=sync_seq,
                        first_seen_at=now, last_seen_at=now, secret_hash=_hash_secret(issued_secret),
                        **{**fields, 'fcm_token': None},
                    )
            except IntegrityError:
                # Lost a create race on installation_id: treat as an update,
                # which must then prove possession like any other.
                installation = AppInstallation.objects.select_for_update().get(installation_id=installation_id)
                created = False
                issued_secret = None
            else:
                _record_history(installation, now)

        if not created:
            ok, issued_secret = _verify_or_claim(installation, secret, user)
            if not ok:
                logger.warning('rejected device sync without a valid installation secret installation_id=%s',
                               installation_id)
                return RegistrationResult(installation=None, rejected=INVALID_SECRET)
            if sync_seq < installation.last_sync_seq:
                logger.info(
                    'ignored stale device sync installation_id=%s sync_seq=%s last_sync_seq=%s',
                    installation_id, sync_seq, installation.last_sync_seq,
                )
                return RegistrationResult(
                    installation=installation, ignored='stale_sync_seq', issued_secret=issued_secret,
                )

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

        push_subscribed = _reconcile_push_subscription(installation=installation, user=user, token=token)
        return RegistrationResult(
            installation=installation, created=created, push_subscribed=push_subscribed,
            issued_secret=issued_secret,
        )


def _reconcile_push_subscription(*, installation, user, token):
    """Keeps notifications.PushSubscription — the one record push delivery
    reads — in step with what an authenticated device just reported, so the
    app needs no second registration call.

    Anonymous syncs never touch it: OptionalTenantJWTAuthentication treats an
    expired/forged token as anonymous, so letting them remove subscriptions
    would let anyone holding an installation_id unsubscribe that device."""
    from apps.notifications import subscriptions

    if user is None or user.tenant_id is None:
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


def unlink_user(*, installation_id, user, sync_seq=None):
    """Logout: remove `user`'s push subscription on this install and clear
    the user link if it is `user`'s. Silent otherwise.

    `sync_seq` (the app's next device-sync counter value) makes logout take
    part in the same ordering as POST /devices/: it is stored as
    `last_sync_seq`, so an authenticated registration that was already in
    flight (lower seq) is ignored as stale instead of re-subscribing a
    logged-out device. Only a caller with a stake in the install can advance
    it: its linked user, or the owner of a subscription on it (an anonymous
    sync may have cleared the link while deliberately keeping that
    subscription)."""
    from apps.notifications import subscriptions

    with transaction.atomic():
        installation = (
            AppInstallation.objects.select_for_update().filter(installation_id=installation_id).first()
        )
        if installation is None:
            return
        removed = subscriptions.remove_for_installation(installation=installation, user=user)
        is_linked_user = installation.user_id == user.id
        if not (is_linked_user or removed):
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
