"""Calendar-month helpers shared by list filters, analytics and exports (D0).

A "month" is the inclusive calendar month in the property's timezone. Every
property runs in settings.TIME_ZONE today (single-timezone product — see
base.py), so the property's month is the local calendar month and every
stored DateField (payment_date, period_start, expense date) is already a
local date. `property_timezones` is the one place to change if properties
ever gain their own zone; responses echo it so clients can show the
"mixed timezones" note without guessing.
"""
import calendar
import re
from datetime import date

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

_MONTH_RE = re.compile(r'^(\d{4})-(\d{2})$')


def local_today():
    """Today in the product timezone. Prefer this over date.today(), which
    follows the container clock (UTC) and is a day behind before 05:30 IST."""
    return timezone.localdate()


def month_start(value):
    return value.replace(day=1)


def month_end(first):
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def add_months(first, count):
    index = first.year * 12 + first.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def month_key(first):
    return first.strftime('%Y-%m')


def parse_month(value, *, param='month', default=None):
    """'YYYY-MM' -> first day of that month. Blank returns `default`."""
    if value in (None, ''):
        return default
    match = _MONTH_RE.match(str(value).strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValidationError({param: [_('Use the format YYYY-MM.')]}, code='invalid_month')
    return date(int(match.group(1)), int(match.group(2)), 1)


def parse_date(value, *, param):
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError({param: [_('Use the format YYYY-MM-DD.')]}, code='invalid_date')


def property_timezones(property_ids=None):
    """Distinct timezones of the given properties — always the product zone
    until properties carry their own (see module docstring)."""
    return [settings.TIME_ZONE]


def next_midnight_ist(now=None):
    """00:00 in the product timezone (IST) on the calendar day *after* `now`,
    even when `now` is exactly 00:00:00. Account-deletion scheduling and retry
    pacing both use it so a failure at midnight is never retried in the same
    nightly run."""
    from datetime import datetime, time, timedelta

    local = timezone.localtime(now or timezone.now())
    tomorrow = local.date() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(tomorrow, time.min))


def first_midnight_ist_at_or_after(moment):
    """The first 00:00 IST that is >= `moment` (an exact midnight stays put)."""
    from datetime import datetime, time

    local = timezone.localtime(moment)
    midnight = timezone.make_aware(datetime.combine(local.date(), time.min))
    return midnight if midnight >= moment else next_midnight_ist(moment)
