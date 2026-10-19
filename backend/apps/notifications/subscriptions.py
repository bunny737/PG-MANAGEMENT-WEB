"""The single writer for `PushSubscription`, the one delivery record for push.

Both registration paths go through here — the web client's
POST /notifications/push-subscriptions/ and the mobile app's POST /devices/
(apps.devices.services.register_installation) — so token ownership rules
live in one place:

- A token identifies a device: the latest login owns it. A row for the same
  token under another user (possibly another tenant, hidden by RLS) is
  dropped as super admin before the upsert.
- A mobile install holds at most one subscription: a rotated token, or a
  previous user's row, on the same install is replaced.
- Only an authenticated owner removes their own rows. Cross-user removals:
  `remove_foreign_for_installation` (someone else authenticates on that
  install) and `remove_all_for_installation` (the device itself, proven by
  its installation secret, reports it is signed out).
"""
from django.db import transaction

from apps.core.tenancy import tenant_context

from .models import PushSubscription


def upsert_subscription(*, user, token, device_type, installation=None, replaces=None):
    """Registers `token` for `user`. `installation=None` leaves an existing
    install link untouched. `replaces` is the caller's previous subscription
    id (web token rotation), deleted in the same transaction. Returns
    (subscription, created)."""
    with transaction.atomic():
        with tenant_context(is_super_admin=True):
            PushSubscription.objects.filter(fcm_token=token).exclude(user=user).delete()
            if installation is not None:
                PushSubscription.objects.filter(installation=installation).exclude(fcm_token=token).delete()
        if replaces is not None:
            PushSubscription.objects.filter(pk=replaces, user=user).exclude(fcm_token=token).delete()

        subscription = PushSubscription.objects.filter(fcm_token=token).first()
        created = subscription is None
        if created:
            subscription = PushSubscription(tenant_id=user.tenant_id, user=user, fcm_token=token)
        subscription.device_type = device_type
        if installation is not None:
            subscription.installation = installation
        subscription.save()
    return subscription, created


def remove_for_installation(*, installation, user):
    """`user`'s own rows on this install (logout, permission revoked)."""
    return PushSubscription.objects.filter(installation=installation, user=user).delete()[0]


def remove_foreign_for_installation(*, installation, keep_user):
    """Every row on this install not owned by `keep_user`, across tenants.
    Runs on each authenticated device registration, so a previous user's
    subscription can't survive an account switch — even when the switch
    isn't detectable because an anonymous sync already cleared the link."""
    with tenant_context(is_super_admin=True):
        return PushSubscription.objects.filter(installation=installation).exclude(user=keep_user).delete()[0]


def remove_all_for_installation(*, installation):
    """Every row on this install, across tenants. Only for a caller that
    proved it is the device itself (its installation secret) while signed
    out — see apps.devices.services._reconcile_push_subscription."""
    with tenant_context(is_super_admin=True):
        return PushSubscription.objects.filter(installation=installation).delete()[0]


def remove_subscription(*, user, subscription_id, if_last_seen_at=None):
    """Deletes `user`'s own row. With `if_last_seen_at` the delete is conditional (one atomic
    DELETE ... WHERE): it only removes the row if no registration has touched it since the caller
    last saw it. A web client's cleanup can arrive late, after the same account turned push off and
    on again — the upsert reuses the row id, so an unconditional DELETE would remove the
    subscription that was just repaired. Returns the number of rows deleted."""
    rows = PushSubscription.objects.filter(pk=subscription_id, user=user)
    if if_last_seen_at is not None:
        rows = rows.filter(last_seen_at=if_last_seen_at)
    return rows.delete()[0]
