"""Resident app access lifecycle (Module 26).

A Resident is the PG's own record and needs no login. A person may create their own app account
(a resident-pool User) and get linked to a record two ways: staff send an INVITE to the record's
email, or the person asks with a PG's JOIN CODE and staff APPROVE the request against a record.
Either way the result is a ResidentAccess row. Nothing here ever creates a User.

Isolation, stated plainly: database RLS isolates TENANTS. Selecting a residency sets
`app.tenant_id`, which admits every row of that PG, so isolation BETWEEN RESIDENTS of one PG is
enforced by the application: every resident endpoint must filter through the selected link's
`resident_id` (see ResidencyScopedAPIView).

Lock order for every writer in this module: **Resident -> ResidentInvite / ResidentAccess /
ResidencyLinkRequest**. It extends the existing exit-workflow order (Resident -> Vacate -> Bed ->
Subscription, see services.lock_resident), so no writer here can deadlock against those.
Credential paths (signup, reset, login) never take part in link locking.
"""
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import timedelta

from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.views import APIView

from apps.accounts.normalization import normalize_email
from apps.audit import log as audit_log
from apps.core.authentication import BLOCKED_TENANT_STATUSES
from apps.core.exceptions import Conflict
from apps.core.models import PlatformConfig
from apps.core.permissions import IsResidentAccount
from apps.core.roles import Role
from apps.core.tenancy import set_tenant_context, tenant_context
from apps.properties.join_codes import normalize_join_code
from apps.properties.models import Property

from .models import Resident, ResidencyLinkRequest, ResidentAccess, ResidentInvite

logger = logging.getLogger(__name__)

INVITE_SALT = 'residents.invite'
RESIDENCY_HEADER = 'HTTP_X_RESIDENCY_ID'

# Who can be offered app access: a record that is, or is about to be, a live resident.
ELIGIBLE_STATUSES = (
    Resident.Status.RESERVED, Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD,
)
EXIT_STATUSES = (
    Resident.Status.VACATED, Resident.Status.ABSCONDED, Resident.Status.BLACKLISTED,
)


# --- Errors ------------------------------------------------------------------------------------
class InviteInvalid(APIException):
    status_code = 400
    default_detail = _('This invitation is invalid or has expired.')
    default_code = 'invite_invalid'


class InviteEmailMismatch(PermissionDenied):
    default_detail = _('This invitation was sent to a different email address.')
    default_code = 'invite_email_mismatch'


class EmailNotVerified(PermissionDenied):
    default_detail = _('Verify your email address first.')
    default_code = 'email_not_verified'


class ResidentNotEligible(APIException):
    status_code = 400
    default_detail = _('App access can only be offered to a reserved, active or notice-period resident.')
    default_code = 'resident_not_eligible'


class ResidentEmailRequired(APIException):
    status_code = 400
    default_detail = _("Add an email address to this resident's record first.")
    default_code = 'resident_email_required'


class ResidentPropertyMismatch(APIException):
    status_code = 400
    default_detail = _('That resident does not belong to the property in the request.')
    default_code = 'resident_property_mismatch'


class RequesterUnavailable(APIException):
    status_code = 400
    default_detail = _("The requester's account is no longer available.")
    default_code = 'requester_unavailable'


class LinkExists(Conflict):
    default_detail = _('This resident already has app access.')
    default_code = 'residency_link_exists'


class LinkRequestNotPending(Conflict):
    default_detail = _('This request has already been resolved.')
    default_code = 'link_request_not_pending'


class ResidencyRequired(APIException):
    status_code = 400
    default_detail = _('Send the residency to act for in the X-Residency-Id header.')
    default_code = 'residency_required'


class ResidencyInactive(PermissionDenied):
    default_detail = _('This residency is not active.')
    default_code = 'residency_inactive'


# --- Scope -------------------------------------------------------------------------------------
class Scope:
    """What a link currently lets its person see. Ranked: each scope includes the ones below."""

    NONE = 'none'
    BILLS = 'bills'          # own invoices, payments, receipts, deposit settlement
    RESERVED = 'reserved'    # + profile and notices (booked but not yet moved in)
    FULL = 'full'            # + everything a living resident uses

    RANK = {NONE: 0, BILLS: 1, RESERVED: 2, FULL: 3}

    @classmethod
    def allows(cls, actual, required):
        return cls.RANK[actual] >= cls.RANK[required] and actual != cls.NONE

    @classmethod
    def narrow_to(cls, actual, ceiling):
        return actual if cls.RANK[actual] <= cls.RANK[ceiling] else ceiling


def residency_scope(access, resident, tenant_status, now=None):
    """The scope of one link right now. Evaluated on every request; no background job decides
    when access ends.

    Precedence: (1) the link itself: revoked or past its expiry => nothing, and nothing below
    can restore it; (2) the resident's status narrows what is left; (3) a suspended tenant
    narrows it to Bills. A later step can only narrow, never widen, so a suspended tenant never
    revives an expired link."""
    now = now or timezone.now()
    if access.status != ResidentAccess.Status.ACTIVE:
        return Scope.NONE
    if access.access_expires_at is not None and now >= access.access_expires_at:
        return Scope.NONE
    if tenant_status == 'deleted':
        return Scope.NONE

    if resident.status in EXIT_STATUSES:
        # Fail closed: an exit that never stamped an expiry (a status written by a path that did
        # not call record_exit) must not become unlimited access.
        if access.access_expires_at is None:
            return Scope.NONE
        scope = Scope.BILLS
    elif resident.status == Resident.Status.RESERVED:
        scope = Scope.RESERVED
    elif resident.status in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
        scope = Scope.FULL
    else:  # inquiry: a lead, not yet a resident
        return Scope.NONE

    if tenant_status in BLOCKED_TENANT_STATUSES:
        scope = Scope.narrow_to(scope, Scope.BILLS)
    return scope


# --- Invite tokens -----------------------------------------------------------------------------
def _hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def make_invite_token(invite, secret):
    """Signed {tenant, invite, secret}. The signed tenant id lets the accept service enter the
    right tenant context from a tamper-proof source, with no cross-tenant lookup."""
    return signing.dumps(
        {'t': str(invite.tenant_id), 'i': str(invite.id), 's': secret}, salt=INVITE_SALT,
    )


def read_invite_token(token):
    try:
        payload = signing.loads(token, salt=INVITE_SALT)
        return uuid.UUID(payload['t']), uuid.UUID(payload['i']), payload['s']
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        raise InviteInvalid()


def mint_invite_secret(invite):
    """Mint (and store the hash of) a fresh secret for a pending invite and return its token.
    Called on the worker that sends the email, so the secret never travels through the broker;
    a retry mints a new one, which voids any earlier undelivered email. Caller holds the row lock."""
    secret = secrets.token_urlsafe(24)
    invite.token_hash = _hash_secret(secret)
    invite.save(update_fields=['token_hash', 'updated_at'])
    return make_invite_token(invite, secret)


# --- Helpers -----------------------------------------------------------------------------------
def lock_resident_row(resident_id):
    """The first lock of every writer in this module (see the module docstring)."""
    return Resident.objects.select_for_update(of=('self',)).get(pk=resident_id)


def require_eligible(resident):
    if resident.status not in ELIGIBLE_STATUSES:
        raise ResidentNotEligible()


def require_verified_resident_account(user):
    if user.role != Role.RESIDENT or not user.is_active:
        raise PermissionDenied(_('This action is for resident app accounts.'), code='resident_account_required')
    if not user.email_verified:
        raise EmailNotVerified()


def active_access_for(resident):
    return ResidentAccess.objects.select_for_update().filter(
        resident=resident, status=ResidentAccess.Status.ACTIVE,
    ).first()


def _cancel_pending_invite(resident, *, reason, actor=None):
    """Retire the resident's pending invite, if any (one pending per resident, by index)."""
    invite = ResidentInvite.objects.select_for_update().filter(
        resident=resident, status=ResidentInvite.Status.PENDING,
    ).first()
    if invite is not None:
        invite.status = ResidentInvite.Status.CANCELLED
        invite.cancel_reason = reason
        invite.cancelled_by = actor
        invite.save(update_fields=['status', 'cancel_reason', 'cancelled_by', 'updated_at'])
    return invite


def invite_is_expired(invite, now=None):
    return invite.status == ResidentInvite.Status.PENDING and (now or timezone.now()) >= invite.expires_at


# --- Staff: invite / cancel / revoke -----------------------------------------------------------
def send_invite(*, resident_id, actor, request=None):
    """Create a pending invite for the resident's recorded email and queue the email. Creates no
    User. A new invite retires the previous pending one, so an old link stops working."""
    from apps.accounts.tasks import send_resident_invite_task
    from apps.core.tasks import enqueue

    with transaction.atomic():
        resident = lock_resident_row(resident_id)
        require_eligible(resident)
        email = normalize_email(resident.email)
        if not email:
            raise ResidentEmailRequired()
        if active_access_for(resident) is not None:
            raise LinkExists()
        _cancel_pending_invite(resident, reason=ResidentInvite.CancelReason.RESENT, actor=actor)
        config = PlatformConfig.get()
        invite = ResidentInvite.objects.create(
            tenant_id=resident.tenant_id, resident=resident, email=email,
            expires_at=timezone.now() + timedelta(hours=config.resident_invite_ttl_hours),
            invited_by=actor,
        )
        audit_log.record(
            action='resident.app_invite_sent', actor=actor, tenant_id=resident.tenant_id, obj=resident,
            after={'invite': str(invite.id), 'expires_at': invite.expires_at.isoformat()}, request=request,
        )
        tenant_id, invite_id = str(invite.tenant_id), str(invite.id)
        transaction.on_commit(lambda: enqueue(send_resident_invite_task, tenant_id, invite_id))
    return invite


def cancel_invite(*, resident_id, actor, request=None):
    """Cancel the resident's pending invite. Idempotent: with none pending it does nothing."""
    with transaction.atomic():
        resident = lock_resident_row(resident_id)
        invite = _cancel_pending_invite(resident, reason=ResidentInvite.CancelReason.STAFF, actor=actor)
        if invite is not None:
            audit_log.record(
                action='resident.app_invite_cancelled', actor=actor, tenant_id=resident.tenant_id,
                obj=resident, after={'invite': str(invite.id)}, request=request,
            )
    return invite


def revoke_access(*, resident_id, actor, request=None):
    """End the resident's app access now. Every scoped request re-checks the link, so logging in
    again does not help. Idempotent. The person keeps their account and any other PG's link."""
    with transaction.atomic():
        resident = lock_resident_row(resident_id)
        access = active_access_for(resident)
        if access is None:
            return None
        now = timezone.now()
        access.status = ResidentAccess.Status.REVOKED
        access.revoked_at = now
        access.revoked_by = actor
        access.save(update_fields=['status', 'revoked_at', 'revoked_by', 'updated_at'])
        audit_log.record(
            action='resident.app_access_revoked', actor=actor, tenant_id=resident.tenant_id, obj=resident,
            before={'access': str(access.id), 'status': 'active'}, after={'status': 'revoked'}, request=request,
        )
    return access


def record_exit(resident):
    """Start the post-exit clock for a resident who has just been set to Vacated / Absconded /
    Blacklisted. Call it inside the workflow's transaction, after the status is set, while the
    resident row is locked. `exited_at` is written only if still null, so Absconded -> Blacklisted
    never restarts (or extends) the window. A pending invite is withdrawn: nobody can newly join
    a record that has left."""
    now = timezone.now()
    config = PlatformConfig.get()
    ResidentAccess.objects.filter(
        resident=resident, status=ResidentAccess.Status.ACTIVE, exited_at__isnull=True,
    ).update(
        exited_at=now, access_expires_at=now + timedelta(days=config.resident_post_exit_access_days),
        updated_at=now,
    )
    ResidentInvite.objects.filter(resident=resident, status=ResidentInvite.Status.PENDING).update(
        status=ResidentInvite.Status.CANCELLED, cancel_reason=ResidentInvite.CancelReason.RESIDENT_LEFT,
        updated_at=now,
    )


# --- Person: accept an invite ------------------------------------------------------------------
def accept_invite(*, user, token, request=None):
    """The signed-in person accepts a staff invite. Returns (access, created).

    Needs a verified email equal to the invite's, so a forwarded link is useless to anyone else.
    Retrying with an invite this user already accepted returns the resulting link in its CURRENT
    state (even revoked or expired); it never creates or reactivates access."""
    tenant_id, invite_id, secret = read_invite_token(token)
    require_verified_resident_account(user)

    with tenant_context(tenant_id), transaction.atomic():  # keeps the caller's app.user_id
        found = ResidentInvite.objects.filter(pk=invite_id, tenant_id=tenant_id).first()
        if found is None:
            raise InviteInvalid()
        resident = lock_resident_row(found.resident_id)
        invite = ResidentInvite.objects.select_for_update().get(pk=found.pk)

        if invite.status == ResidentInvite.Status.ACCEPTED:
            if invite.accepted_by_id == user.pk and invite.resulting_access_id:
                return ResidentAccess.objects.get(pk=invite.resulting_access_id), False
            raise InviteInvalid()
        if (
            invite.status != ResidentInvite.Status.PENDING
            or invite_is_expired(invite)
            or not hmac.compare_digest(invite.token_hash, _hash_secret(secret))
        ):
            raise InviteInvalid()
        if normalize_email(user.email) != invite.email:
            raise InviteEmailMismatch()
        require_eligible(resident)

        if active_access_for(resident) is not None:
            raise LinkExists()
        now = timezone.now()
        access = ResidentAccess.objects.create(
            tenant_id=resident.tenant_id, user=user, resident=resident,
            origin=ResidentAccess.Origin.INVITE, granted_by=invite.invited_by, activated_at=now,
        )
        invite.status = ResidentInvite.Status.ACCEPTED
        invite.accepted_by = user
        invite.accepted_at = now
        invite.resulting_access = access
        invite.save(update_fields=['status', 'accepted_by', 'accepted_at', 'resulting_access', 'updated_at'])
        # Only THIS person's own pending request for this PG is satisfied. Other people's
        # requests for the same PG stay pending for staff.
        ResidencyLinkRequest.objects.filter(
            requester=user, property_id=resident.property_id, status=ResidencyLinkRequest.Status.PENDING,
        ).update(
            status=ResidencyLinkRequest.Status.CANCELLED,
            cancel_reason=ResidencyLinkRequest.CancelReason.ACCESS_GRANTED, updated_at=now,
        )
        audit_log.record(
            action='resident.app_access_granted', actor=user, tenant_id=resident.tenant_id, obj=resident,
            after={'access': str(access.id), 'origin': 'invite'}, request=request,
        )
    return access, True


# --- Person: ask to be linked ------------------------------------------------------------------
def lookup_join_code(raw_code):
    """Resolve a join code to {property_id, tenant_id, name, city}, or raise a generic 404.

    This is the one deliberate cross-tenant read for a resident-pool person: they have no tenant,
    and the code is exactly what tells us which tenant to enter. It runs as super admin for this
    single exact-match query and returns four fields; the code identifies a PG and nothing else.
    Inactive properties and blocked tenants resolve like an unknown code."""
    from apps.accounts.models import Tenant

    code = normalize_join_code(raw_code)
    if code is None:
        raise NotFound(_('That join code was not found.'), code='join_code_not_found')
    with tenant_context(is_super_admin=True):
        row = Property.objects.filter(join_code=code, status=Property.Status.ACTIVE).values(
            'id', 'tenant_id', 'name', 'city',
        ).first()
        if row is not None:
            tenant_status = Tenant.objects.filter(pk=row['tenant_id']).values_list('status', flat=True).first()
            if tenant_status is None or tenant_status in BLOCKED_TENANT_STATUSES:
                row = None
    if row is None:
        raise NotFound(_('That join code was not found.'), code='join_code_not_found')
    return {'property_id': row['id'], 'tenant_id': row['tenant_id'], 'name': row['name'], 'city': row['city']}


def request_residency_link(*, user, property_id, tenant_id, message='', claimed_name='',
                           claimed_phone='', claimed_room='', request=None):
    """Create (or return the existing) pending request to be linked to a property. Returns
    (link_request, created). Requires a verified email. The tenant comes from a resolved join
    code (or, in Module 25, a published listing), never from the caller."""
    require_verified_resident_account(user)
    with tenant_context(tenant_id), transaction.atomic():
        if ResidentAccess.objects.filter(
            user=user, resident__property_id=property_id, status=ResidentAccess.Status.ACTIVE,
        ).exists():
            raise LinkExists(_('You are already linked to this PG.'))
        existing = ResidencyLinkRequest.objects.filter(
            requester=user, property_id=property_id, status=ResidencyLinkRequest.Status.PENDING,
        ).first()
        if existing is not None:
            return existing, False
        try:
            with transaction.atomic():
                link_request = ResidencyLinkRequest.objects.create(
                    tenant_id=tenant_id, requester=user, property_id=property_id, message=message,
                    claimed_name=claimed_name, claimed_phone=claimed_phone, claimed_room=claimed_room,
                )
        except IntegrityError:  # a concurrent identical request won
            return ResidencyLinkRequest.objects.get(
                requester=user, property_id=property_id, status=ResidencyLinkRequest.Status.PENDING,
            ), False
        audit_log.record(
            action='resident.link_requested', actor=user, tenant_id=tenant_id, obj=link_request,
            after={'property': str(property_id)}, request=request,
        )
        transaction.on_commit(lambda: _notify_link_requested(link_request.pk, tenant_id))
    return link_request, True


def cancel_link_request(*, user, link_request_id, request=None):
    """The requester withdraws their own pending request. Idempotent for an already-cancelled one."""
    require_verified_resident_account(user)
    mine = ResidencyLinkRequest.objects.filter(pk=link_request_id, requester_id=user.pk).first()  # user clause
    if mine is None:
        raise NotFound(_('Request not found.'), code='not_found')
    with tenant_context(mine.tenant_id), transaction.atomic():
        link_request = ResidencyLinkRequest.objects.select_for_update().get(pk=mine.pk)
        if link_request.status == ResidencyLinkRequest.Status.CANCELLED:
            return link_request
        if link_request.status != ResidencyLinkRequest.Status.PENDING:
            raise LinkRequestNotPending()
        link_request.status = ResidencyLinkRequest.Status.CANCELLED
        link_request.cancel_reason = ResidencyLinkRequest.CancelReason.REQUESTER
        link_request.resolved_at = timezone.now()
        link_request.save(update_fields=['status', 'cancel_reason', 'resolved_at', 'updated_at'])
        audit_log.record(
            action='resident.link_request_cancelled', actor=user, tenant_id=link_request.tenant_id,
            obj=link_request, request=request,
        )
    return link_request


# --- Staff: resolve link requests --------------------------------------------------------------
def approve_link_request(*, link_request_id, resident_id, actor, request=None):
    """Link the requester to the chosen resident record. Returns (access, created).

    Staff choose the record; nothing is auto-matched. The record must belong to the request's
    property (and so its tenant), and the caller's view has already limited the request to the
    actor's visible properties. Retrying an approved request with the same record returns the
    same link."""
    with transaction.atomic():
        resident = lock_resident_row(resident_id)
        link_request = ResidencyLinkRequest.objects.select_for_update().get(pk=link_request_id)

        if link_request.status == ResidencyLinkRequest.Status.APPROVED:
            if link_request.resolved_resident_id == resident.pk and link_request.resulting_access_id:
                return ResidentAccess.objects.get(pk=link_request.resulting_access_id), False
            raise LinkRequestNotPending()
        if link_request.status != ResidencyLinkRequest.Status.PENDING:
            raise LinkRequestNotPending()
        if resident.property_id != link_request.property_id or resident.tenant_id != link_request.tenant_id:
            raise ResidentPropertyMismatch()
        require_eligible(resident)

        from apps.accounts.models import User

        requester = User.objects.resident_pool().filter(pk=link_request.requester_id, is_active=True).first()
        if requester is None or not requester.email_verified:
            raise RequesterUnavailable()
        if active_access_for(resident) is not None:
            raise LinkExists()

        now = timezone.now()
        access = ResidentAccess.objects.create(
            tenant_id=resident.tenant_id, user=requester, resident=resident,
            origin=ResidentAccess.Origin.LINK_REQUEST, granted_by=actor, activated_at=now,
        )
        link_request.status = ResidencyLinkRequest.Status.APPROVED
        link_request.resolved_by = actor
        link_request.resolved_at = now
        link_request.resolved_resident = resident
        link_request.resulting_access = access
        link_request.save(update_fields=[
            'status', 'resolved_by', 'resolved_at', 'resolved_resident', 'resulting_access', 'updated_at',
        ])
        # Granting access any way retires the offer made the other way.
        _cancel_pending_invite(resident, reason=ResidentInvite.CancelReason.ACCESS_GRANTED, actor=actor)
        audit_log.record(
            action='resident.app_access_granted', actor=actor, tenant_id=resident.tenant_id, obj=resident,
            after={'access': str(access.id), 'origin': 'link_request', 'requester': str(requester.pk)},
            request=request,
        )
        transaction.on_commit(lambda: _notify_link_resolved(link_request.pk, resident.tenant_id))
    return access, True


def reject_link_request(*, link_request_id, actor, note='', request=None):
    with transaction.atomic():
        link_request = ResidencyLinkRequest.objects.select_for_update().get(pk=link_request_id)
        if link_request.status == ResidencyLinkRequest.Status.REJECTED:
            return link_request
        if link_request.status != ResidencyLinkRequest.Status.PENDING:
            raise LinkRequestNotPending()
        link_request.status = ResidencyLinkRequest.Status.REJECTED
        link_request.resolved_by = actor
        link_request.resolved_at = timezone.now()
        link_request.resolution_note = note
        link_request.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note', 'updated_at'])
        audit_log.record(
            action='resident.link_request_rejected', actor=actor, tenant_id=link_request.tenant_id,
            obj=link_request, after={'note': note}, request=request,
        )
        tenant_id = link_request.tenant_id
        transaction.on_commit(lambda: _notify_link_resolved(link_request.pk, tenant_id))
    return link_request


# --- Notifications (queued after commit; best effort) ------------------------------------------
def _notify_link_requested(link_request_id, tenant_id):
    from apps.core.tasks import enqueue
    from apps.notifications.tasks import notify_link_requested_task

    enqueue(notify_link_requested_task, str(tenant_id), str(link_request_id))


def _notify_link_resolved(link_request_id, tenant_id):
    from apps.core.tasks import enqueue
    from apps.notifications.tasks import notify_link_resolved_task

    enqueue(notify_link_resolved_task, str(tenant_id), str(link_request_id))


# --- The selected residency, for resident endpoints --------------------------------------------
def resolve_residency(request, required=Scope.FULL):
    """Validate `X-Residency-Id` for the signed-in resident-pool user and enter that tenant.

    Order: the link must be this user's (looked up through the user clause, never by id alone);
    its scope is computed now; only then is the tenant entered, for the rest of the request
    (the middleware clears it). Returns (access, resident, scope).

    Database RLS now admits every row of that PG, so the caller MUST filter its own queries by
    `resident_id` of the returned link."""
    from apps.accounts.models import Tenant

    raw = request.META.get(RESIDENCY_HEADER)
    if not raw:
        raise ResidencyRequired()
    try:
        access_id = uuid.UUID(raw)
    except ValueError:
        raise ResidencyRequired()
    access = ResidentAccess.objects.filter(pk=access_id, user_id=request.user.pk).first()
    if access is None:
        # Same answer for "not yours" and "does not exist".
        raise PermissionDenied(_('That residency is not available.'), code='residency_not_found')

    set_tenant_context(tenant_id=access.tenant_id, user_id=request.user.pk)
    resident = Resident.objects.get(pk=access.resident_id)
    tenant_status = Tenant.objects.filter(pk=access.tenant_id).values_list('status', flat=True).first()
    scope = residency_scope(access, resident, tenant_status)
    if not Scope.allows(scope, required):
        raise ResidencyInactive()
    return access, resident, scope


class ResidencyScopedAPIView(APIView):
    """Base for resident endpoints that act inside one PG (Module 26b builds on it). Subclasses
    set `required_scope`; `self.residency`, `self.resident` and `self.scope` are set before the
    handler runs. Remember the isolation note in the module docstring."""

    permission_classes = [IsResidentAccount]
    required_scope = Scope.FULL

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentication, permissions, throttles
        self.residency, self.resident, self.scope = resolve_residency(request, self.required_scope)


def link_request_recipients(prop):
    """Who hears about a new link request: the tenant's Owner(s), and the property's assigned
    staff who may manage residents. Mirrors the auto-billing summary's recipient rule."""
    from django.contrib.auth import get_user_model

    from apps.core.modules import resolve_permissions

    user_model = get_user_model()
    recipients = {
        user.pk: user
        for user in user_model.objects.filter(tenant_id=prop.tenant_id, role=Role.OWNER, is_active=True)
    }
    for user in user_model.objects.filter(
        tenant_id=prop.tenant_id, is_active=True, property_assignments__property=prop,
    ):
        if 'manage_residents' in resolve_permissions(user):
            recipients[user.pk] = user
    return list(recipients.values())
