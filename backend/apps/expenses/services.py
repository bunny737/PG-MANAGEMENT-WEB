"""Expense writes and queries (UX roadmap D5). Views stay thin; every
mutation is audit-logged here (invariant 9)."""
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.audit import log as audit_log
from apps.core.idempotency import key_reused

from .models import SYSTEM_CATEGORIES, Expense, ExpenseCategory

ZERO = Decimal('0.00')
AUDIT_FIELDS = ('property_id', 'category_id', 'amount', 'date', 'payment_mode', 'note')

# Magic-byte sniffing (the client-sent Content-Type is not trusted).
_SIGNATURES = (
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'%PDF-', 'application/pdf'),
)


def ensure_system_categories(tenant_id):
    """Seed the tenant's missing system categories. Idempotent and race-safe
    (the partial unique constraint + ignore_conflicts)."""
    existing = set(
        ExpenseCategory.objects.filter(tenant_id=tenant_id, is_system=True).values_list('code', flat=True)
    )
    missing = [
        ExpenseCategory(tenant_id=tenant_id, code=code, is_system=True, order=index)
        for index, code in enumerate(SYSTEM_CATEGORIES) if code not in existing
    ]
    if missing:
        ExpenseCategory.objects.bulk_create(missing, ignore_conflicts=True)


def live_expenses():
    return Expense.objects.filter(deleted_at__isnull=True)


def snapshot(expense):
    return {
        field.removesuffix('_id'): None if getattr(expense, field) is None else str(getattr(expense, field))
        for field in AUDIT_FIELDS
    } | {'has_attachment': bool(expense.attachment)}


def sniff_attachment(upload):
    """Validate size and real type; returns the detected content type."""
    if upload.size > settings.EXPENSE_ATTACHMENT_MAX_BYTES:
        raise ValidationError(
            {'attachment': [_('The file is larger than %(mb)s MB.')
                            % {'mb': settings.EXPENSE_ATTACHMENT_MAX_BYTES // (1024 * 1024)}]},
            code='attachment_too_large',
        )
    head = upload.read(16)
    upload.seek(0)
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    raise ValidationError(
        {'attachment': [_('Attach a JPEG, PNG, WebP or PDF file.')]}, code='attachment_type_not_allowed',
    )


def _store_attachment(expense, upload):
    if expense.attachment:
        expense.attachment.delete(save=False)
    expense.attachment_content_type = sniff_attachment(upload)
    expense.attachment.save(upload.name or 'attachment', upload, save=False)


@transaction.atomic
def create_expense(*, data, attachment=None, actor, request=None, idempotency_key=None):
    if idempotency_key:
        existing = live_expenses().filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return _replay(existing, data)
    expense = Expense(
        tenant_id=actor.tenant_id, created_by=actor, updated_by=actor,
        idempotency_key=idempotency_key, **data,
    )
    if attachment is not None:
        expense.attachment_content_type = sniff_attachment(attachment)
    try:
        with transaction.atomic():
            expense.save()
    except IntegrityError:
        if not idempotency_key:
            raise
        # A concurrent request with the same key committed first.
        existing = Expense.objects.filter(idempotency_key=idempotency_key).first()
        if existing is None:
            raise
        return _replay(existing, data)
    if attachment is not None:
        _store_attachment(expense, attachment)
        expense.save(update_fields=['attachment', 'attachment_content_type', 'updated_at'])
    expense.replayed = False
    audit_log.record(
        action='expense.created', actor=actor, obj=expense, after=snapshot(expense), request=request,
    )
    return expense


def _replay(existing, data):
    same = (
        existing.property_id == data['property'].pk
        and existing.amount == data['amount']
        and existing.date == data['date']
    )
    if not same:
        raise key_reused()
    existing.replayed = True
    return existing


@transaction.atomic
def update_expense(*, expense, data, actor, request=None):
    before = snapshot(expense)
    for field, value in data.items():
        setattr(expense, field, value)
    expense.updated_by = actor
    expense.save()
    after = snapshot(expense)
    if before != after:
        audit_log.record(
            action='expense.updated', actor=actor, obj=expense, before=before, after=after, request=request,
        )
    return expense


@transaction.atomic
def delete_expense(*, expense, actor, request=None):
    """Soft delete: excluded from every total and export from now on."""
    expense.deleted_at = timezone.now()
    expense.deleted_by = actor
    expense.save(update_fields=['deleted_at', 'deleted_by', 'updated_at'])
    audit_log.record(
        action='expense.deleted', actor=actor, obj=expense, before=snapshot(expense), request=request,
    )


@transaction.atomic
def replace_attachment(*, expense, upload, actor, request=None):
    _store_attachment(expense, upload)
    expense.updated_by = actor
    expense.save(update_fields=['attachment', 'attachment_content_type', 'updated_by', 'updated_at'])
    audit_log.record(
        action='expense.attachment_replaced', actor=actor, obj=expense,
        after={'content_type': expense.attachment_content_type}, request=request,
    )
    return expense


@transaction.atomic
def remove_attachment(*, expense, actor, request=None):
    if expense.attachment:
        expense.attachment.delete(save=False)
    expense.attachment = None
    expense.attachment_content_type = ''
    expense.updated_by = actor
    expense.save(update_fields=['attachment', 'attachment_content_type', 'updated_by', 'updated_at'])
    audit_log.record(
        action='expense.attachment_removed', actor=actor, obj=expense, request=request,
    )
    return expense


def summary(queryset):
    """{total, count, by_category[]} for an already-filtered live queryset."""
    totals = queryset.aggregate(total=Sum('amount'), count=Count('id'))
    rows = (
        queryset.order_by().values('category_id')
        .annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    )
    categories = {c.id: c for c in ExpenseCategory.objects.filter(id__in=[r['category_id'] for r in rows])}
    return {
        'total': str(totals['total'] or ZERO),
        'count': totals['count'],
        'by_category': [
            {
                'category': str(row['category_id']),
                'name': str(categories[row['category_id']].label),
                'code': categories[row['category_id']].code or None,
                'total': str(row['total']),
                'count': row['count'],
            }
            for row in rows
        ],
    }


def total_for(property_ids, first, last):
    """expenses_paid (D0): live expenses dated within [first, last]."""
    value = live_expenses().filter(property_id__in=property_ids, date__range=(first, last)).aggregate(
        total=Sum('amount')
    )['total']
    return value if value is not None else ZERO
