"""Resident app access (Module 26): how a person's own login account gets linked to a resident
record a PG keeps.

A `Resident` is the PG's record (admission, allocation, billing) and needs no login. An app
account is a resident-pool `User` the person creates themselves. Three tables connect them:

- ResidentInvite       a pending offer from staff to an email address. Never creates a User.
- ResidencyLinkRequest the person's request to be linked to a PG; staff approve against a record.
- ResidentAccess       the link itself, created only by accepting an invite or approving a request.

All three are tenant tables under RLS (`tenant_id`). ResidentAccess and ResidencyLinkRequest
also let the person they are about read them (`user_id` / `requester_id` = app.user_id; SELECT
only), because a resident account has no tenant of its own.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin


class ResidentAccess(TenantModelMixin):
    """One person's access to one resident record. One person can hold several (a resident of
    two PGs); one record has at most one `active` link at a time (partial unique index)."""

    class Origin(models.TextChoices):
        INVITE = 'invite', _('Staff invite')
        LINK_REQUEST = 'link_request', _('Link request')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        REVOKED = 'revoked', _('Revoked')
        # Set by the nightly tidy once access_expires_at has passed. Access is denied at the
        # timestamp itself (apps.residents.access.residency_scope), never because of this flag.
        EXPIRED = 'expired', _('Expired')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='residencies',
    )
    resident = models.ForeignKey(
        'residents.Resident', on_delete=models.PROTECT, related_name='app_accesses',
    )
    origin = models.CharField(max_length=15, choices=Origin.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    activated_at = models.DateTimeField()
    # Set when the resident leaves (Vacated / Absconded / Blacklisted), only if still null so a
    # later Absconded -> Blacklisted never restarts the clock. access_expires_at is the single
    # authoritative end of the post-exit window; the scope check compares it to now().
    exited_at = models.DateTimeField(null=True, blank=True)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    class Meta:
        db_table = 'resident_access'
        constraints = [
            models.UniqueConstraint(
                fields=['resident'], condition=Q(status='active'),
                name='one_active_access_per_resident',
            ),
        ]
        indexes = [models.Index(fields=['user', 'status'], name='resident_access_user_idx')]

    def __str__(self):
        return f'{self.user_id} -> {self.resident_id} [{self.status}]'


class ResidentInvite(TenantModelMixin):
    """A pending offer of app access, addressed to an email. Sending one never creates a User:
    the person signs up (or logs in) themselves, verifies the email and accepts. The token is
    signed (it names the tenant) and only the hash of its secret is stored."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        ACCEPTED = 'accepted', _('Accepted')
        EXPIRED = 'expired', _('Expired')
        CANCELLED = 'cancelled', _('Cancelled')

    class CancelReason(models.TextChoices):
        STAFF = 'staff', _('Cancelled by staff')
        RESENT = 'resent', _('Replaced by a newer invite')
        ACCESS_GRANTED = 'access_granted', _('Access was granted another way')
        RESIDENT_LEFT = 'resident_left', _('The resident left')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.ForeignKey(
        'residents.Resident', on_delete=models.PROTECT, related_name='app_invites',
    )
    # Copied from the resident record when sent. The invite is for this address; a later edit
    # of the record does not retarget an outstanding invite.
    email = models.EmailField()
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    cancel_reason = models.CharField(max_length=15, choices=CancelReason.choices, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    # What accepting created. A retry returns THIS link in its current state (even revoked or
    # expired); it never creates or reactivates access.
    resulting_access = models.ForeignKey(
        ResidentAccess, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    class Meta:
        db_table = 'resident_invites'
        constraints = [
            models.UniqueConstraint(
                fields=['resident'], condition=Q(status='pending'),
                name='one_pending_invite_per_resident',
            ),
        ]

    def __str__(self):
        return f'invite {self.id} [{self.status}]'


class ResidencyLinkRequest(TenantModelMixin):
    """A person asking to be linked to a PG. It names a *property* (what a join code or a listing
    identifies), not a resident: staff pick the matching resident record when they approve."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        CANCELLED = 'cancelled', _('Cancelled')

    class CancelReason(models.TextChoices):
        REQUESTER = 'requester', _('Cancelled by the requester')
        ACCESS_GRANTED = 'access_granted', _('Access was granted another way')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='link_requests',
    )
    property = models.ForeignKey(
        'properties.Property', on_delete=models.PROTECT, related_name='link_requests',
    )
    message = models.CharField(max_length=500, blank=True)
    # What the person says about themselves, to help staff find the record. Display only:
    # nothing here is trusted or matched automatically.
    claimed_name = models.CharField(max_length=100, blank=True)
    claimed_phone = models.CharField(max_length=15, blank=True)
    claimed_room = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    cancel_reason = models.CharField(max_length=15, choices=CancelReason.choices, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=200, blank=True)
    resolved_resident = models.ForeignKey(
        'residents.Resident', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # What approving created, so retrying an approval returns the same link.
    resulting_access = models.ForeignKey(
        ResidentAccess, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    class Meta:
        db_table = 'residency_link_requests'
        constraints = [
            models.UniqueConstraint(
                fields=['requester', 'property'], condition=Q(status='pending'),
                name='one_pending_link_request_per_user_property',
            ),
        ]
        indexes = [models.Index(fields=['property', 'status'], name='link_request_prop_status_idx')]

    def __str__(self):
        return f'link request {self.id} [{self.status}]'
