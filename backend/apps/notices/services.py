"""Notices and food holidays (Module 24): the write paths behind the API.

Every food-holiday write locks the property's PropertySettings row first, then
the holiday row (NO KEY UPDATE, so credit rows referencing it are never
blocked by their foreign-key check), then lets apps.notices.credits lock each
affected resident — the global order in that module's docstring. The
Settings lock also serializes the overlap check, so two concurrent creates
can't both slip past it.
"""
from django.db import transaction
from django.utils import formats
from django.utils.translation import gettext as _

from apps.audit import log as audit_log
from apps.core.exceptions import Conflict

from . import credits
from .models import Announcement, FoodHoliday

FINANCIAL_FIELDS = ('start_date', 'end_date', 'adjust_in_bill', 'rate_per_day')
HOLIDAY_FIELDS = ('name',) + FINANCIAL_FIELDS


def _lock_settings(property_id, tenant_id):
    from apps.billing.services import lock_property_settings

    return lock_property_settings(property_id, tenant_id)


def lock_holiday_property(holiday):
    """First lock of any credit write on this holiday (e.g. restore)."""
    return _lock_settings(holiday.property_id, holiday.tenant_id)


def _snapshot(holiday):
    return {field: None if getattr(holiday, field) is None else str(getattr(holiday, field))
            for field in HOLIDAY_FIELDS}


def _check_overlap(holiday):
    clash = FoodHoliday.objects.filter(
        property_id=holiday.property_id, start_date__lte=holiday.end_date, end_date__gte=holiday.start_date,
    )
    if holiday.pk is not None:
        clash = clash.exclude(pk=holiday.pk)
    other = clash.order_by('start_date').first()
    if other is not None:
        raise Conflict(
            _('These dates overlap "%(name)s" (%(start)s – %(end)s).') % {
                'name': other.name, 'start': _date(other.start_date), 'end': _date(other.end_date),
            },
            code='holiday_overlap',
        )


def _date(value):
    return formats.date_format(value, 'j M Y')


# --- Auto-generated notice text ----------------------------------------------

def notice_text(holiday):
    """(title, body) of the notice posted for a holiday. Says whether food
    charges are adjusted, never the rate — notices are readable without
    finance access (and later by residents)."""
    days = holiday.total_days
    title = _('%(name)s: no food from %(start)s to %(end)s') % {
        'name': holiday.name, 'start': _date(holiday.start_date), 'end': _date(holiday.end_date),
    }
    if days == 1:
        body = _('Food will not be served on %(start)s for %(name)s. You can stay as usual.') % {
            'start': _date(holiday.start_date), 'name': holiday.name,
        }
    else:
        body = _('Food will not be served from %(start)s to %(end)s (%(days)s days) for %(name)s. '
                 'You can stay as usual.') % {
            'start': _date(holiday.start_date), 'end': _date(holiday.end_date), 'days': days,
            'name': holiday.name,
        }
    if holiday.adjust_in_bill:
        body = '%s %s' % (body, _('Food charges for these days will be adjusted in your next bill.'))
    return title, body


def _write_auto_text(announcement, holiday):
    announcement.title, announcement.body = notice_text(holiday)
    announcement.is_auto_text = True
    announcement.generated_from = holiday.snapshot()
    announcement.save(update_fields=['title', 'body', 'is_auto_text', 'generated_from', 'updated_at'])


def notice_outdated(announcement):
    """A customised holiday notice whose holiday changed since the owner last
    confirmed the text (edit or "mark current"). Derived, so it survives a
    reload; auto text is regenerated instead, so it is never outdated."""
    holiday = getattr(announcement, 'food_holiday', None)
    if holiday is None or announcement.is_auto_text:
        return False
    return announcement.generated_from != holiday.snapshot()


# --- Food holidays ------------------------------------------------------------

@transaction.atomic
def create_holiday(*, data, post_notice, actor, request=None):
    prop = data['property']
    _lock_settings(prop.pk, prop.tenant_id)
    holiday = FoodHoliday(tenant_id=prop.tenant_id, created_by=actor, **data)
    _check_overlap(holiday)
    holiday.save()
    if post_notice:
        announcement = Announcement(
            tenant_id=holiday.tenant_id, property=prop, category=Announcement.Category.HOLIDAY,
            created_by=actor,
        )
        announcement.title, announcement.body = notice_text(holiday)
        announcement.is_auto_text = True
        announcement.generated_from = holiday.snapshot()
        announcement.save()
        holiday.announcement = announcement
        holiday.save(update_fields=['announcement', 'updated_at'])
        audit_log.record(action='announcement.created', actor=actor, obj=announcement,
                         after={'title': announcement.title, 'holiday': str(holiday.pk)}, request=request)
    audit_log.record(action='food_holiday.created', actor=actor, obj=holiday, after=_snapshot(holiday),
                     request=request)
    credits.recompute_holiday(holiday, actor=actor, request=request)
    return holiday


@transaction.atomic
def update_holiday(*, holiday, data, actor, request=None):
    _lock_settings(holiday.property_id, holiday.tenant_id)
    holiday = FoodHoliday.objects.select_for_update(no_key=True).get(pk=holiday.pk)
    before = _snapshot(holiday)
    financial_change = any(field in data and data[field] != getattr(holiday, field) for field in FINANCIAL_FIELDS)
    if financial_change and credits.holiday_is_locked(holiday):
        raise Conflict(
            _('This holiday is already on an issued bill or a settlement, so its dates, rate and '
              'bill adjustment can no longer change.'),
            code='holiday_locked',
        )
    for field, value in data.items():
        setattr(holiday, field, value)
    _check_overlap(holiday)
    holiday.save()
    after = _snapshot(holiday)
    if before != after:
        audit_log.record(action='food_holiday.updated', actor=actor, obj=holiday, before=before, after=after,
                         request=request)
    if financial_change:
        credits.recompute_holiday(holiday, actor=actor, request=request)
    announcement = _locked_announcement(holiday)
    if announcement is not None and announcement.is_auto_text and announcement.generated_from != holiday.snapshot():
        before = {'title': announcement.title, 'body': announcement.body}
        _write_auto_text(announcement, holiday)
        audit_log.record(action='announcement.regenerated', actor=actor, obj=announcement, before=before,
                         after={'title': announcement.title, 'body': announcement.body}, request=request)
    return holiday


def _locked_announcement(holiday):
    """The holiday's notice, row-locked and re-read, so an owner's concurrent
    text edit either commits first (and is seen as customised) or waits —
    it is never overwritten by regenerated text. Locked last: notice edits
    take only this lock, so the order can't cycle."""
    if holiday.announcement_id is None:
        return None
    return Announcement.objects.select_for_update().filter(pk=holiday.announcement_id).first()


@transaction.atomic
def delete_holiday(*, holiday, actor, request=None):
    _lock_settings(holiday.property_id, holiday.tenant_id)
    holiday = FoodHoliday.objects.select_for_update(no_key=True).get(pk=holiday.pk)
    if credits.holiday_is_locked(holiday):
        raise Conflict(
            _('This holiday is already on an issued bill or a settlement, so it cannot be deleted.'),
            code='holiday_locked',
        )
    credits.delete_holiday_credits(holiday, actor=actor, request=request)
    announcement = _locked_announcement(holiday)
    audit_log.record(action='food_holiday.deleted', actor=actor, obj=holiday, before=_snapshot(holiday),
                     request=request)
    holiday.delete()
    if announcement is not None and announcement.is_auto_text:
        # Still the generated text: it only described this holiday. A notice
        # the owner rewrote is kept (now unlinked).
        audit_log.record(action='announcement.deleted', actor=actor, obj=announcement,
                         before={'title': announcement.title}, request=request)
        announcement.delete()


# --- Announcements ------------------------------------------------------------

def create_announcement(*, data, actor, request=None):
    prop = data['property']
    announcement = Announcement.objects.create(tenant_id=prop.tenant_id, created_by=actor, **data)
    audit_log.record(action='announcement.created', actor=actor, obj=announcement,
                     after={'title': announcement.title, 'category': announcement.category}, request=request)
    return announcement


@transaction.atomic
def update_announcement(*, announcement, data, actor, request=None):
    announcement = Announcement.objects.select_for_update().get(pk=announcement.pk)
    before = {'title': announcement.title, 'body': announcement.body, 'category': announcement.category,
              'is_pinned': announcement.is_pinned,
              'expires_on': announcement.expires_on.isoformat() if announcement.expires_on else None}
    text_changed = any(field in data and data[field] != getattr(announcement, field) for field in ('title', 'body'))
    for field, value in data.items():
        setattr(announcement, field, value)
    if text_changed:
        announcement.is_auto_text = False
        holiday = getattr(announcement, 'food_holiday', None)
        if holiday is not None:
            # Edited knowing the holiday as it is now: the text is current.
            announcement.generated_from = holiday.snapshot()
    announcement.save()
    after = {'title': announcement.title, 'body': announcement.body, 'category': announcement.category,
             'is_pinned': announcement.is_pinned,
             'expires_on': announcement.expires_on.isoformat() if announcement.expires_on else None}
    if before != after:
        audit_log.record(action='announcement.updated', actor=actor, obj=announcement, before=before,
                         after=after, request=request)
    return announcement


@transaction.atomic
def mark_current(*, announcement, actor, request=None):
    """The owner checked a customised holiday notice still reads right after
    the holiday changed: clear the outdated warning without editing it."""
    announcement = Announcement.objects.select_for_update().get(pk=announcement.pk)
    holiday = getattr(announcement, 'food_holiday', None)
    if holiday is None:
        return announcement
    announcement.generated_from = holiday.snapshot()
    announcement.save(update_fields=['generated_from', 'updated_at'])
    audit_log.record(action='announcement.marked_current', actor=actor, obj=announcement,
                     after={'holiday': str(holiday.pk)}, request=request)
    return announcement


def delete_announcement(*, announcement, actor, request=None):
    audit_log.record(action='announcement.deleted', actor=actor, obj=announcement,
                     before={'title': announcement.title}, request=request)
    announcement.delete()  # a linked holiday keeps going (SET_NULL)
