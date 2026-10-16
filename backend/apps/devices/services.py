import logging
from dataclasses import dataclass
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AppInstallation, AppInstallationHistory

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    installation: Optional[AppInstallation]
    created: bool = False
    ignored: Optional[str] = None
    # True/False once an authenticated sync reconciled the push subscription;
    # None when it wasn't evaluated (anonymous sync, stale sync_seq).
    push_subscribed: Optional[bool] = None


def register_installation(*, installation_id, sync_seq, signed_in, fields, user):
    """Upsert one install. `user` is the authenticated user or None (anonymous).

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
        if installation is not None and sync_seq < installation.last_sync_seq:
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

        now = timezone.now()
        created = installation is None
        if created:
            try:
                with transaction.atomic():
                    installation = AppInstallation.objects.create(
                        installation_id=installation_id, user=user, last_sync_seq=sync_seq,
                        first_seen_at=now, last_seen_at=now, **fields,
                    )
            except IntegrityError:
                # Lost a create race on installation_id: fall through to update.
                installation = AppInstallation.objects.select_for_update().get(installation_id=installation_id)
                created = False
            else:
                _record_history(installation, now)

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
        return RegistrationResult(installation=installation, created=created, push_subscribed=push_subscribed)


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
    logged-out device. Only the install's owner can advance it."""
    from apps.notifications import subscriptions

    with transaction.atomic():
        installation = (
            AppInstallation.objects.select_for_update().filter(installation_id=installation_id).first()
        )
        if installation is None:
            return
        subscriptions.remove_for_installation(installation=installation, user=user)
        if installation.user_id != user.id:
            return
        installation.user = None
        update_fields = ['user']
        if sync_seq is not None and sync_seq > installation.last_sync_seq:
            installation.last_sync_seq = sync_seq
            update_fields.append('last_sync_seq')
        installation.save(update_fields=update_fields)
