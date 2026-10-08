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


def register_installation(*, installation_id, sync_seq, signed_in, fields, user):
    """Upsert one install. `user` is the authenticated user or None (anonymous).

    - Stale `sync_seq` (< stored) is ignored wholesale; equal is reprocessed.
    - Authenticated: link to `user` (last writer wins). Anonymous with
      signed_in=False: unlink. Anonymous with signed_in=True: leave as is.
    - A FCM token belongs to one install: it is nulled on any other holder.
    - A history row is written on first sighting and whenever the build or
      OS version changes.
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
                return RegistrationResult(installation=installation, created=True)

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
        return RegistrationResult(installation=installation, created=False)


def _record_history(installation, now):
    AppInstallationHistory.objects.create(
        installation=installation, build_number=installation.build_number,
        version_name=installation.version_name, os_version=installation.os_version, recorded_at=now,
    )


def unlink_user(*, installation_id, user):
    """Clear the user link only if it is `user`'s. Silent otherwise."""
    AppInstallation.objects.filter(installation_id=installation_id, user=user).update(user=None)
