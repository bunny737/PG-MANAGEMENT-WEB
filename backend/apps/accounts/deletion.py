"""Account deletion (Module 22): request, cancel, and the nightly purge.

A user asks to delete their account (an Owner's request deletes the whole business). The account
is locked at once (apps.core.authentication) and, once the grace period has passed, the 00:00 IST
beat task (`purge_due_account_deletions`) purges it in durable, resumable phases:

    notify -> razorpay_close (tenant) -> db_purge -> files_purge (tenant) -> complete

Each phase runs under a lease on the request row (`claim_token`), stamps its own `*_at` and can be
rerun. A failing request is paced by `next_attempt_at`, never retried in a tight loop, and parked
as `failed` after `PlatformConfig.account_deletion_max_attempts` nightly attempts — still locked,
until a Super Admin retries it (or, while still reversible, resolves it as cancelled).

`DISPOSITION` is the inventory of every model: what a tenant purge and a staff purge do with it.
A test fails if a model is missing, so a future module cannot forget to say what happens to its data.
"""
import logging
import uuid
from collections import Counter
from datetime import timedelta

from django.apps import apps as django_apps
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import F, Q, TextField
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit import log as audit_log
from apps.audit.models import AuditLog
from apps.core.exceptions import Conflict
from apps.core.models import ContactMessage, PlatformConfig
from apps.core.periods import first_midnight_ist_at_or_after, next_midnight_ist
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from . import otp
from .models import ACTIVE_DELETION_STATUSES, AccountDeletionRequest, Tenant, User

logger = logging.getLogger(__name__)

Status = AccountDeletionRequest.Status
Scope = AccountDeletionRequest.Scope

# A claimed request whose worker has not heartbeat for this long is taken over by the next run.
LEASE_TIMEOUT = timedelta(minutes=15)
# files_purge refreshes the lease at least this often (and every HEARTBEAT_OBJECTS deletes).
HEARTBEAT_SECONDS = 60
HEARTBEAT_OBJECTS = 100

# Roles that may delete their own account through this flow. Super Admins are platform staff
# (never self-service); residents have no login yet. Role checks use `user.role`, never
# `tenant_id is None` (which a future tenant-less resident would also satisfy).
SELF_SERVICE_ROLES = (Role.OWNER, Role.MANAGER, Role.RECEPTIONIST)

# ---------------------------------------------------------------------------------------------
# Data inventory
# ---------------------------------------------------------------------------------------------
PURGE, REDACT, RETAIN, PLATFORM, SELF = 'purge', 'redact', 'retain', 'platform', 'self'

# label -> (what a TENANT purge does, what a STAFF purge does).
#   purge    rows are deleted
#   redact   rows stay but their personal content is removed
#   retain   rows stay untouched (tax/billing history, or records other people own)
#   platform not user data
#   self     the deletion request itself
DISPOSITION = {
    'accounts.AccountDeletionRequest': (SELF, SELF),
    'accounts.OtpCode': (PURGE, PURGE),
    'accounts.Tenant': (RETAIN, RETAIN),
    'accounts.User': (PURGE, PURGE),
    'audit.AuditLog': (PURGE, REDACT),
    'billing.Discount': (PURGE, RETAIN),
    'billing.Invoice': (PURGE, RETAIN),
    'billing.InvoiceLineItem': (PURGE, RETAIN),
    'billing.Payment': (PURGE, RETAIN),
    'billing.ReceiptCounter': (PURGE, RETAIN),
    'core.ContactMessage': (PURGE, PURGE),
    'core.PlatformConfig': (PLATFORM, PLATFORM),
    'devices.AppInstallation': (PURGE, PURGE),
    'devices.AppInstallationHistory': (PURGE, PURGE),
    'devices.AppVersionPolicy': (PLATFORM, PLATFORM),
    'expenses.Expense': (PURGE, RETAIN),
    'expenses.ExpenseCategory': (PURGE, RETAIN),
    'notifications.NotificationLog': (PURGE, PURGE),
    'notifications.NotificationPreference': (PURGE, PURGE),
    'notifications.NotificationTemplate': (PLATFORM, PLATFORM),
    'notifications.PushSubscription': (PURGE, PURGE),
    'notifications.ScheduledNotification': (PURGE, PURGE),
    'operations.Complaint': (PURGE, RETAIN),
    'operations.ComplaintComment': (PURGE, RETAIN),
    'operations.Visitor': (PURGE, RETAIN),
    'properties.Bed': (PURGE, RETAIN),
    'properties.Building': (PURGE, RETAIN),
    'properties.FeatureCatalog': (PLATFORM, PLATFORM),
    'properties.Floor': (PURGE, RETAIN),
    'properties.Property': (PURGE, RETAIN),
    'properties.PropertyFeature': (PURGE, RETAIN),
    'properties.PropertyImage': (PURGE, RETAIN),
    'properties.PropertySettings': (PURGE, RETAIN),
    'properties.PropertyStaffAssignment': (PURGE, PURGE),
    'properties.Room': (PURGE, RETAIN),
    'properties.TenantFeature': (PURGE, RETAIN),
    'residents.AbscondedRecord': (PURGE, RETAIN),
    'residents.Admission': (PURGE, RETAIN),
    'residents.Allocation': (PURGE, RETAIN),
    'residents.BlacklistEntry': (PURGE, RETAIN),
    'residents.Resident': (PURGE, RETAIN),
    'residents.Transfer': (PURGE, RETAIN),
    'residents.Vacate': (PURGE, RETAIN),
    # Billing history is kept (GST / tax records); only personal payloads are redacted.
    'subscriptions.BedLedgerEntry': (RETAIN, RETAIN),
    'subscriptions.Plan': (PLATFORM, PLATFORM),
    'subscriptions.PlanBedTier': (PLATFORM, PLATFORM),
    'subscriptions.RazorpaySubscription': (RETAIN, RETAIN),
    'subscriptions.RazorpayWebhookEvent': (REDACT, RETAIN),
    'subscriptions.Subscription': (RETAIN, RETAIN),
    'subscriptions.SubscriptionInvoice': (RETAIN, RETAIN),
    'subscriptions.SubscriptionInvoiceLine': (RETAIN, RETAIN),
    'subscriptions.SubscriptionPayment': (REDACT, RETAIN),
}

# Tenant-scoped models a tenant purge deletes with `.filter(tenant_id=...)`, children before the
# rows that PROTECT-reference them (Payment -> Invoice, Admission -> Bed, Resident -> Property ...).
# A test asserts this is exactly the set of TenantModelMixin models marked PURGE above.
PURGE_ORDER = [
    'billing.Payment', 'billing.InvoiceLineItem', 'billing.Invoice', 'billing.Discount', 'billing.ReceiptCounter',
    'operations.ComplaintComment', 'operations.Complaint', 'operations.Visitor',
    'residents.Vacate', 'residents.Transfer', 'residents.Allocation', 'residents.Admission',
    'residents.AbscondedRecord', 'residents.BlacklistEntry',
    'expenses.Expense', 'expenses.ExpenseCategory',
    'notifications.NotificationLog', 'notifications.ScheduledNotification',
    'notifications.NotificationPreference', 'notifications.PushSubscription',
    'properties.PropertyFeature', 'properties.TenantFeature', 'properties.PropertyImage',
    'properties.PropertyStaffAssignment', 'properties.PropertySettings',
    'properties.Bed', 'properties.Room', 'properties.Floor', 'properties.Building',
    'residents.Resident', 'properties.Property',
]

# Object-storage prefixes that hold a tenant's uploads (see each model's upload_to).
STORAGE_PREFIXES = ('residents', 'properties', 'complaints', 'expenses')


class LeaseLost(Exception):
    """Another worker took over this request; stop without touching it."""


# ---------------------------------------------------------------------------------------------
# Request / cancel
# ---------------------------------------------------------------------------------------------
def can_request_deletion(user):
    """Role-based on purpose — see SELF_SERVICE_ROLES."""
    return user.role in SELF_SERVICE_ROLES


def confirm_methods(user):
    """How `user` can confirm a deletion request right now; clients only offer what works.
    Email codes work today; phone codes need an SMS backend (`otp.sms_delivery_available`)."""
    methods = []
    if user.has_usable_password():
        methods.append('password')
    if user.email:
        methods.append('otp_email')
    if user.phone and otp.sms_delivery_available():
        methods.append('otp_phone')
    return methods


def scheduled_for(requested_at, grace_days):
    """requested_at + grace_days x 24h, rounded UP to the next 00:00 IST: never less than the full
    grace period, and the purge lands on that night's run."""
    return first_midnight_ist_at_or_after(requested_at + timedelta(days=grace_days))


def create_request(user, *, reason='', created_by=None, request=None, now=None):
    """Creates the deletion request for `user` and locks the account. An Owner's request deletes
    the whole business (scope=tenant); a Manager's or Receptionist's only themselves.

    Ends every existing session (auth_version) — the requester's own too, so callers return a fresh
    token pair — and queues the confirmation email after commit. A second ACTIVE request, whoever
    makes it, is a 409 (the partial unique constraints are the arbiter of races)."""
    if not can_request_deletion(user):
        raise Conflict(_('This account type cannot be deleted from here.'), code='deletion_not_allowed')
    now = now or timezone.now()
    config = PlatformConfig.get()
    with transaction.atomic():
        locked = User.objects.select_for_update(of=('self',)).select_related('tenant').get(pk=user.pk)
        scope = Scope.TENANT if locked.role == Role.OWNER else Scope.USER
        when = scheduled_for(now, config.account_deletion_grace_days)
        try:
            with transaction.atomic():
                deletion = AccountDeletionRequest.objects.create(
                    user=locked, tenant=locked.tenant, scope=scope,
                    requested_at=now, scheduled_for=when, next_attempt_at=when,
                    reason=(reason or '')[:500],
                )
        except IntegrityError:
            raise Conflict(_('A deletion request already exists for this account.'), code='deletion_already_requested')
        # End every session: the account's own, or — for the Owner — everyone in the business.
        targets = User.objects.filter(tenant_id=locked.tenant_id) if scope == Scope.TENANT else User.objects.filter(pk=locked.pk)
        targets.update(auth_version=F('auth_version') + 1)
        audit_log.record(
            action='account.deletion_requested', actor=created_by or locked, tenant_id=locked.tenant_id,
            obj=deletion, after={'scope': scope, 'scheduled_for': when.isoformat(), 'on_behalf': created_by is not None},
            request=request,
        )
        request_id = str(deletion.id)

        def _queue_confirmation():
            from apps.core.tasks import enqueue

            from .tasks import send_account_deletion_requested_task

            enqueue(send_account_deletion_requested_task, request_id)

        transaction.on_commit(_queue_confirmation)
    return deletion


def can_cancel(deletion, user):
    """The requester (user scope) or the tenant's Owner (tenant scope), while still pending."""
    if deletion.status != Status.PENDING:
        return False
    if deletion.scope == Scope.TENANT:
        return user.role == Role.OWNER and user.tenant_id is not None and user.tenant_id == deletion.tenant_id
    return deletion.user_id == user.pk


def cancel_request(deletion, *, actor, request=None):
    """The user (or tenant Owner) cancels a PENDING request within the grace period."""
    with transaction.atomic():
        locked = AccountDeletionRequest.objects.select_for_update().get(pk=deletion.pk)
        if locked.status != Status.PENDING:
            raise Conflict(_('This deletion request can no longer be cancelled.'), code='deletion_not_cancellable')
        _mark_cancelled(locked, actor=actor, request=request)
    return locked


def resolve_as_cancelled(deletion, *, actor, note, request=None):
    """Super Admin: resolve a pending or failed request as cancelled — only while nothing
    irreversible has run. After Razorpay closure / the database purge the only way out is
    retry-to-completion."""
    with transaction.atomic():
        locked = AccountDeletionRequest.objects.select_for_update().get(pk=deletion.pk)
        if locked.status not in (Status.PENDING, Status.FAILED) or not locked.is_reversible:
            raise Conflict(_('This deletion request can no longer be cancelled.'), code='deletion_not_cancellable')
        notified = locked.notified_at is not None
        _mark_cancelled(locked, actor=actor, request=request, note=note)
        if notified and locked.user_id:
            user_id = str(locked.user_id)

            def _queue_notice():
                from apps.core.tasks import enqueue

                from .tasks import send_account_deletion_cancelled_task

                enqueue(send_account_deletion_cancelled_task, user_id)

            transaction.on_commit(_queue_notice)
    return locked


def _mark_cancelled(deletion, *, actor, request=None, note=''):
    deletion.status = Status.CANCELLED
    deletion.cancelled_at = timezone.now()
    deletion.reason = ''
    deletion.claim_token = None
    deletion.claimed_at = None
    deletion.save(update_fields=['status', 'cancelled_at', 'reason', 'claim_token', 'claimed_at'])
    audit_log.record(
        action='account.deletion_cancelled', actor=actor, tenant_id=deletion.tenant_id, obj=deletion,
        after={'scope': deletion.scope, 'note_given': bool(note)}, request=request,
    )


def retry_now(deletion, *, actor, request=None):
    """Super Admin: put a failed (or waiting) request back in the queue immediately and run it
    through the same claim as the scheduler, after the reset commits."""
    with transaction.atomic():
        locked = AccountDeletionRequest.objects.select_for_update().get(pk=deletion.pk)
        # A request still inside its grace period is not "stuck" — it is waiting, and running it now
        # would skip the period the user was promised. Only failed ones (or ones already due) retry.
        retryable = locked.status == Status.FAILED or (
            locked.status == Status.PENDING and locked.scheduled_for <= timezone.now()
        )
        if not retryable:
            raise Conflict(_('Only a failed deletion request can be retried.'), code='deletion_not_retryable')
        locked.status = Status.PENDING
        locked.attempts = 0
        locked.next_attempt_at = timezone.now()
        locked.save(update_fields=['status', 'attempts', 'next_attempt_at'])
        audit_log.record(
            action='account.deletion_retried', actor=actor, tenant_id=locked.tenant_id, obj=locked,
            after={'scope': locked.scope}, request=request,
        )
        pk = locked.pk
        transaction.on_commit(lambda: run_one(pk))
    return locked


# ---------------------------------------------------------------------------------------------
# Claim / run
# ---------------------------------------------------------------------------------------------
def due_request_ids(now=None):
    now = now or timezone.now()
    return list(
        AccountDeletionRequest.objects.filter(
            Q(status=Status.PENDING, next_attempt_at__lte=now)
            | Q(status=Status.PROCESSING, claimed_at__lt=now - LEASE_TIMEOUT)
        ).order_by('next_attempt_at').values_list('pk', flat=True)
    )


def claim(request_id=None, *, now=None):
    """The one claim used by the beat task, the admin "retry now" action and tests. Takes a row lock
    with SKIP LOCKED and converts it to a lease in the same transaction, so two workers can never
    both own a request, and a row a live worker is mid-phase on (it holds the row lock) is skipped.
    Also takes over a PROCESSING row whose lease expired, whatever its `next_attempt_at`."""
    now = now or timezone.now()
    with transaction.atomic():
        due = AccountDeletionRequest.objects.select_for_update(skip_locked=True).filter(
            Q(status=Status.PENDING, next_attempt_at__lte=now)
            | Q(status=Status.PROCESSING, claimed_at__lt=now - LEASE_TIMEOUT)
        )
        if request_id is not None:
            due = due.filter(pk=request_id)
        row = due.order_by('next_attempt_at').first()
        if row is None:
            return None
        row.status = Status.PROCESSING
        row.claim_token = uuid.uuid4()
        row.claimed_at = now
        # The free-text reason is only for whoever reads the pending request; once the purge has
        # started it has no use, so it never survives into processing (or a later retry).
        row.reason = ''
        row.save(update_fields=['status', 'claim_token', 'claimed_at', 'reason'])
    return row


def run_due_requests(now=None):
    """What the nightly task does: a snapshot of the ids due now, each claimed and processed once.
    The snapshot (and the failure pacing in `next_attempt_at`) is why a failing request is attempted
    once per run, never in a loop."""
    now = now or timezone.now()
    outcomes = Counter()
    for pk in due_request_ids(now):
        row = claim(pk, now=now)
        if row is None:
            continue
        outcomes[process(row)] += 1
    failed = AccountDeletionRequest.objects.filter(status=Status.FAILED).count()
    open_refunds = _open_refund_count()
    logger.info(
        'account deletion run: %s; %s failed request(s) awaiting a Super Admin; %s refund(s) pending',
        dict(outcomes) or 'nothing due', failed, open_refunds,
    )
    return dict(outcomes)


def run_one(request_id):
    row = claim(request_id)
    return process(row) if row is not None else None


def _open_refund_count():
    from apps.subscriptions.models import SubscriptionPayment

    with tenant_context(is_super_admin=True):
        return SubscriptionPayment.objects.filter(refund_status=SubscriptionPayment.RefundStatus.PENDING).count()


def _lock(request_id, token):
    """The request row under FOR UPDATE, only if this worker still holds the lease."""
    row = AccountDeletionRequest.objects.select_for_update().filter(
        pk=request_id, claim_token=token, status=Status.PROCESSING,
    ).first()
    if row is None:
        raise LeaseLost()
    return row


def _stamp(request_id, token, **fields):
    """Conditional UPDATE on the lease. Never `save()` a stale in-memory copy: the purge may have
    nulled the row's user/tenant FKs, and a full save would put them back."""
    updated = AccountDeletionRequest.objects.filter(
        pk=request_id, claim_token=token, status=Status.PROCESSING,
    ).update(**fields)
    if not updated:
        raise LeaseLost()


def process(row):
    """Runs a claimed request through its phases. Returns 'completed', 'retry', 'failed' or
    'lease_lost'."""
    token = row.claim_token
    phases = TENANT_PHASES if row.scope == Scope.TENANT else USER_PHASES
    current_phase = 'start'
    try:
        for name, stamp_field, run in phases:
            current = AccountDeletionRequest.objects.get(pk=row.pk)
            if current.claim_token != token or current.status != Status.PROCESSING:
                raise LeaseLost()
            current_phase = name
            if name != 'complete' and getattr(current, stamp_field) is not None:
                continue
            run(current, token)
        return 'completed'
    except LeaseLost:
        return 'lease_lost'
    except Exception as exc:  # noqa: BLE001 - any failure is recorded and retried on a later night
        return _record_failure(row.pk, token, current_phase, exc)


def _record_failure(request_id, token, phase, exc):
    config = PlatformConfig.get()
    with transaction.atomic():
        row = AccountDeletionRequest.objects.select_for_update().filter(pk=request_id, claim_token=token).first()
        if row is None:
            return 'lease_lost'
        row.attempts += 1
        # Class and phase only: an exception message can carry the data it choked on.
        row.last_error = f'{phase}: {type(exc).__name__}'[:200]
        row.claim_token = None
        row.claimed_at = None
        if row.attempts >= config.account_deletion_max_attempts:
            row.status = Status.FAILED
        else:
            row.status = Status.PENDING
            row.next_attempt_at = next_midnight_ist()
        row.save(update_fields=['attempts', 'last_error', 'claim_token', 'claimed_at', 'status', 'next_attempt_at'])
        failed = row.status == Status.FAILED
        error, attempts = row.last_error, row.attempts
    logger.warning('account deletion %s failed in %s (attempt %s): %s', request_id, phase, attempts, type(exc).__name__,
                   exc_info=exc)
    if failed:
        logger.error('account_deletion_failed request=%s last_error=%s', request_id, error,
                     extra={'event': 'account_deletion_failed', 'request_id': str(request_id)})
        try:
            from apps.core.tasks import enqueue

            from .tasks import notify_super_admins_deletion_failed_task

            enqueue(notify_super_admins_deletion_failed_task, str(request_id))
        except Exception:  # noqa: BLE001 - alerting must never mask the failure itself
            logger.exception('could not queue the Super Admin alert for %s', request_id)
        return 'failed'
    return 'retry'


# ---------------------------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------------------------
def _phase_notify(row, token):
    """Mandatory publish, best-effort delivery. Done first, while the user still exists, because a
    purged account has no address left to tell. See the module docs for the guarantee."""
    user = User.objects.filter(pk=row.user_id).first() if row.user_id else None
    channel, address = AccountDeletionRequest.NoticeChannel.NONE, ''
    if user is not None:
        if user.email:
            channel, address = AccountDeletionRequest.NoticeChannel.EMAIL, user.email
        elif user.phone and otp.sms_delivery_available():
            channel, address = AccountDeletionRequest.NoticeChannel.SMS, user.phone
    if address:
        from .tasks import send_account_deletion_begun_task

        # Straight to .delay(), NOT apps.core.tasks.enqueue: that swallows broker outages, and a
        # purge must not advance past a notice it never managed to queue. A crash between this
        # call and the stamp below can send the notice twice on rerun; that is accepted.
        send_account_deletion_begun_task.delay(str(row.id), address, str(channel), user.language_code)
    _stamp(row.pk, token, notified_at=timezone.now(), notice_channel=str(channel))


def _phase_razorpay_close(row, token):
    from apps.subscriptions import services as subscription_services

    with transaction.atomic():
        locked = _lock(row.pk, token)
        tenant = Tenant.objects.filter(pk=locked.tenant_id).first()
        if tenant is not None:
            subscription_services.close_billing_for_deletion(tenant)
        _stamp(row.pk, token, razorpay_closed_at=timezone.now())


def _phase_db_purge(row, token):
    with transaction.atomic():
        locked = _lock(row.pk, token)
        if locked.scope == Scope.TENANT:
            counts = purge_tenant_rows(locked.tenant_id, exclude_request=locked.pk)
        else:
            counts = purge_user_rows(locked.user_id, locked.tenant_id)
        _stamp(row.pk, token, db_purged_at=timezone.now())
    logger.info('account deletion %s database purge: %s', row.pk, dict(counts))


def _phase_files_purge(row, token):
    """Deletes the tenant's uploads. No database work here beyond the heartbeat, so the lease is
    refreshed by time as well as by count: a slow listing or a few large objects can't outlast it."""
    state = {'since': timezone.now(), 'n': 0}

    def heartbeat(objects=1):
        # `objects=0` is a pure time check, used around each directory listing.
        state['n'] += objects
        if state['n'] >= HEARTBEAT_OBJECTS or (timezone.now() - state['since']).total_seconds() >= HEARTBEAT_SECONDS:
            _stamp(row.pk, token, claimed_at=timezone.now())
            state['since'], state['n'] = timezone.now(), 0

    purge_tenant_files(row.tenant_id, heartbeat=heartbeat)
    _stamp(row.pk, token, files_purged_at=timezone.now())


def _phase_complete(row, token):
    with transaction.atomic():
        locked = _lock(row.pk, token)
        if locked.scope == Scope.TENANT and locked.tenant_id:
            # The tenant row stays as the tax tombstone (its legal name is kept). DELETED is only
            # set now that every login is gone, so the failed/pending screens stay reachable until then.
            Tenant.objects.filter(pk=locked.tenant_id).update(status=Tenant.Status.DELETED, updated_at=timezone.now())
        AccountDeletionRequest.objects.filter(pk=locked.pk, claim_token=token).update(
            status=Status.COMPLETED, completed_at=timezone.now(), reason='', last_error='',
            claim_token=None, claimed_at=None,
        )
        audit_log.record(
            action='account.deleted', tenant_id=None, obj=locked,
            after={'request_id': str(locked.pk), 'scope': locked.scope},
        )


TENANT_PHASES = [
    ('notify', 'notified_at', _phase_notify),
    ('razorpay_close', 'razorpay_closed_at', _phase_razorpay_close),
    ('db_purge', 'db_purged_at', _phase_db_purge),
    ('files_purge', 'files_purged_at', _phase_files_purge),
    ('complete', 'completed_at', _phase_complete),
]
USER_PHASES = [
    ('notify', 'notified_at', _phase_notify),
    ('db_purge', 'db_purged_at', _phase_db_purge),
    ('complete', 'completed_at', _phase_complete),
]


# ---------------------------------------------------------------------------------------------
# Purge implementations
# ---------------------------------------------------------------------------------------------
def _model(label):
    return django_apps.get_model(label)


def purge_tenant_rows(tenant_id, *, exclude_request=None):
    """Deletes (or redacts) everything the inventory says a tenant purge owns. Safe to rerun."""
    counts = Counter()
    with tenant_context(tenant_id, is_super_admin=True):
        # Pending staff requests of this business are moot once it is gone. A staff request that
        # is already processing is left alone: both purges are idempotent.
        AccountDeletionRequest.objects.filter(
            tenant_id=tenant_id, scope=Scope.USER, status=Status.PENDING,
        ).exclude(pk=exclude_request).update(
            status=Status.SUPERSEDED, reason='', claim_token=None, claimed_at=None,
        )

        for label in PURGE_ORDER:
            _total, per_model = _model(label).objects.filter(tenant_id=tenant_id).delete()
            for deleted_label, n in per_model.items():
                counts[deleted_label] += n

        counts['audit.AuditLog'] += AuditLog.objects.filter(tenant_id=tenant_id).delete()[0]

        _redact_tenant_billing(tenant_id)

        users = list(User.objects.filter(tenant_id=tenant_id).values_list('pk', 'email', 'phone'))
        user_ids = [pk for pk, _, _ in users]
        emails = [e for _, e, _ in users if e]
        phones = [p for _, _, p in users if p]
        _delete_user_side_records(user_ids, emails, phones, counts)
        counts['accounts.User'] += User.objects.filter(tenant_id=tenant_id).delete()[0]
    return counts


def purge_user_rows(user_id, tenant_id):
    """A Manager's or Receptionist's own purge: their login and personal records; the business's
    records they created stay, with the user reference nulled (those FKs are SET_NULL)."""
    counts = Counter()
    user = User.objects.filter(pk=user_id).first() if user_id else None
    if user is None:
        return counts  # already gone: the phase is done
    with tenant_context(tenant_id, is_super_admin=True):
        _redact_user_audit(user, counts)
        NotificationLog = _model('notifications.NotificationLog')
        counts['notifications.NotificationLog'] += NotificationLog.objects.filter(recipient_user=user).delete()[0]
        _delete_user_side_records(
            [user.pk], [user.email] if user.email else [], [user.phone] if user.phone else [], counts,
        )
        counts['accounts.User'] += user.delete()[0]
    return counts


def _delete_user_side_records(user_ids, emails, phones, counts):
    """Records tied to a login by something other than a cascading FK."""
    AppInstallation = _model('devices.AppInstallation')
    counts['devices.AppInstallation'] += AppInstallation.objects.filter(user_id__in=user_ids).delete()[0]
    contact = Q()
    for email in emails:
        contact |= Q(email__iexact=email)
    if phones:
        contact |= Q(phone__in=phones)
    if contact:
        counts['core.ContactMessage'] += ContactMessage.objects.filter(contact).delete()[0]


def _redact_user_audit(user, counts):
    """Audit rows keep their action and timing but lose what identifies the user: the IP of actions
    they performed, and any row whose before/after text names them — by value, so legacy rows such as
    property-assignment events (which store the staff email/phone) are covered without listing call
    sites."""
    base = AuditLog.objects.filter(tenant_id=user.tenant_id)
    counts['audit.AuditLog(ip)'] += base.filter(actor_id=user.pk).update(ip_address=None)

    needles = [str(user.pk)] + [value for value in (user.email, user.phone) if value]
    named = Q(object_type='User', object_id=str(user.pk))
    for needle in needles:
        named |= Q(before_text__icontains=needle) | Q(after_text__icontains=needle)
    rows = base.annotate(
        before_text=Cast('before', TextField()), after_text=Cast('after', TextField()),
    ).filter(named)
    for row_id, before, after in list(rows.values_list('pk', 'before', 'after')):
        AuditLog.objects.filter(pk=row_id).update(
            before={'redacted': True} if before is not None else None,
            after={'redacted': True} if after is not None else None,
        )
        counts['audit.AuditLog(redacted)'] += 1


def _redact_tenant_billing(tenant_id):
    """Razorpay payloads hold the customer's contact details. The retained billing rows keep only
    the allow-listed scalars (subscriptions.services.sanitized_payload)."""
    from apps.subscriptions.models import (
        RazorpaySubscription, RazorpayWebhookEvent, Subscription, SubscriptionInvoice, SubscriptionPayment,
    )
    from apps.subscriptions.services import sanitized_payload

    SubscriptionPayment.objects.filter(tenant_id=tenant_id).update(raw_payload={})

    subscription_ids = list(Subscription.objects.filter(tenant_id=tenant_id).values_list('pk', flat=True))
    ledger_ids = list(
        RazorpaySubscription.objects.filter(subscription_id__in=subscription_ids)
        .values_list('razorpay_subscription_id', flat=True)
    )
    invoices = list(SubscriptionInvoice.objects.filter(tenant_id=tenant_id).values_list('pk', 'razorpay_invoice_id'))
    receipts = [str(pk) for pk, _ in invoices]
    razorpay_invoice_ids = [rid for _, rid in invoices if rid]

    match = Q(tenant_id=tenant_id)
    if ledger_ids:
        match |= Q(razorpay_subscription_id__in=ledger_ids)
    # Invoice events were stored without a tenant before Module 22: find them by the same keys the
    # webhook handler uses (the invoice's Razorpay id, or its receipt = our invoice id).
    if razorpay_invoice_ids:
        match |= Q(payload__payload__invoice__entity__id__in=razorpay_invoice_ids)
    if receipts:
        match |= Q(payload__payload__invoice__entity__receipt__in=receipts)
    for event_id, payload in list(RazorpayWebhookEvent.objects.filter(match).values_list('pk', 'payload')):
        RazorpayWebhookEvent.objects.filter(pk=event_id).update(
            payload=sanitized_payload(payload), tenant_id=tenant_id,
        )


def _iter_storage_files(prefix, heartbeat=lambda objects=1: None):
    """Every object under `prefix` (works for local storage and GCS), one directory at a time so
    nothing larger than a single listing is held in memory. `heartbeat(0)` runs before and after
    each listing: a slow listing can't outlast the lease unnoticed, and a worker that lost the
    lease stops here rather than after the whole prefix has been enumerated."""
    heartbeat(0)
    try:
        directories, files = default_storage.listdir(prefix)
    except (FileNotFoundError, NotADirectoryError):
        return
    heartbeat(0)
    for name in files:
        yield f'{prefix}/{name}'
    for directory in directories:
        yield from _iter_storage_files(f'{prefix}/{directory}', heartbeat)


def purge_tenant_files(tenant_id, *, heartbeat=lambda objects=1: None):
    """Deletes a tenant's uploads, streaming list and delete together. Idempotent: a prefix that is
    already empty is simply done."""
    deleted = 0
    for root in STORAGE_PREFIXES:
        prefix = f'{root}/{tenant_id}'
        for path in _iter_storage_files(prefix, heartbeat):
            default_storage.delete(path)
            deleted += 1
            heartbeat()
    return deleted


def active_request_for(user):
    return AccountDeletionRequest.objects.active_for(user).order_by('-requested_at').first()


__all__ = [
    'ACTIVE_DELETION_STATUSES', 'DISPOSITION', 'PURGE_ORDER', 'can_cancel', 'can_request_deletion', 'cancel_request',
    'claim', 'confirm_methods', 'create_request', 'process', 'resolve_as_cancelled', 'retry_now',
    'run_due_requests', 'scheduled_for',
]
