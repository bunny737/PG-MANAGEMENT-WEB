import re
from django.db import migrations


def _normalize_email(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.lower()


def _normalize_phone(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    digits = re.sub(r'\D', '', s)
    if len(digits) == 10:
        canonical = digits
    elif len(digits) == 11 and digits.startswith('0'):
        canonical = digits[1:]
    elif len(digits) == 12 and digits.startswith('91'):
        canonical = digits[2:]
    else:
        raise ValueError('Invalid phone number format.')

    if not re.match(r'^[6-9]\d{9}$', canonical):
        raise ValueError('Invalid phone number format.')

    return canonical


def _mask(val):
    if val is None:
        return 'None'
    s = str(val).strip()
    if not s:
        return 'empty'
    if len(s) <= 3:
        return '***'
    return f'***{s[-3:]}'


def normalize_and_validate_users(apps, schema_editor):
    User = apps.get_model('accounts', 'User')

    errors = []
    normalized_records = []
    active_emails = {}
    active_phones = {}

    for user in User.objects.all():
        raw_email = user.email
        raw_phone = user.phone

        # 1. Normalization
        norm_email = None
        email_err = None
        try:
            norm_email = _normalize_email(raw_email)
        except ValueError as exc:
            email_err = str(exc)

        norm_phone = None
        phone_err = None
        try:
            norm_phone = _normalize_phone(raw_phone)
        except ValueError as exc:
            phone_err = str(exc)

        if email_err:
            errors.append(f"User {user.id} ({user.role}): malformed email ({_mask(raw_email)})")
        if phone_err:
            errors.append(f"User {user.id} ({user.role}): malformed phone ({_mask(raw_phone)})")

        # 2. Invariant checks against normalized values
        if user.role in ('owner', 'super_admin') and norm_email is None:
            errors.append(f"User {user.id} ({user.role}): requires email, got {_mask(raw_email)}")

        if user.role in ('manager', 'receptionist') and norm_phone is None:
            errors.append(f"User {user.id} ({user.role}): requires phone, got {_mask(raw_phone)}")

        if norm_email is None and norm_phone is None:
            errors.append(f"User {user.id} ({user.role}): requires at least one of email or phone")

        # 3. Active collisions
        if user.is_active:
            if norm_email:
                if norm_email in active_emails:
                    errors.append(
                        f"Active email collision between user {user.id} and {active_emails[norm_email]}: {_mask(norm_email)}"
                    )
                else:
                    active_emails[norm_email] = user.id

            if norm_phone:
                if norm_phone in active_phones:
                    errors.append(
                        f"Active phone collision between user {user.id} and {active_phones[norm_phone]}: {_mask(norm_phone)}"
                    )
                else:
                    active_phones[norm_phone] = user.id

        normalized_records.append((user, norm_email, norm_phone))

    if errors:
        raise RuntimeError(
            "User identifier migration aborted due to invariant violations:\n"
            + "\n".join(f"  - {err}" for err in errors)
        )

    for user, norm_email, norm_phone in normalized_records:
        if user.email != norm_email or user.phone != norm_phone:
            user.email = norm_email
            user.phone = norm_phone
            user.save(update_fields=['email', 'phone'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_schema_prep'),
    ]

    operations = [
        migrations.RunPython(normalize_and_validate_users, reverse_code=migrations.RunPython.noop),
    ]
