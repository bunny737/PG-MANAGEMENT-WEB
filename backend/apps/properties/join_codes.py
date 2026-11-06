"""Property join codes (Module 26).

A join code is a short random string a resident types (or scans) to ask to be linked to a PG.
It identifies the property and NOTHING else: possessing it grants no access, it only lets a
signed-in, email-verified person create a *pending* link request that staff must approve.

Codes are random (`secrets`), never sequential, drawn from an alphabet without look-alike
characters, and always stored and compared upper-case.
"""
import re
import secrets

# No 0/O, 1/I: codes are read off a notice board and typed on a phone.
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
LENGTH = 8

_SHAPE = re.compile(rf'^[{ALPHABET}]{{{LENGTH}}}$')


def generate_join_code():
    return ''.join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalize_join_code(raw):
    """Upper-cased code with the separators people type removed, or None if it cannot be a code
    (so a malformed lookup never reaches the database)."""
    if not isinstance(raw, str):
        return None
    code = re.sub(r'[\s-]', '', raw).upper()
    return code if _SHAPE.match(code) else None


def rotate_join_code(property_id, *, actor, request=None):
    """Replace a property's join code. The old one stops working at once; link requests already
    made with it stay valid. Audited without recording either code (they are semi-secret)."""
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from apps.audit import log as audit_log

    from .models import Property

    with transaction.atomic():
        prop = Property.objects.select_for_update().get(pk=property_id)
        for _attempt in range(5):
            prop.join_code = generate_join_code()
            prop.join_code_rotated_at = timezone.now()
            try:
                with transaction.atomic():
                    prop.save(update_fields=['join_code', 'join_code_rotated_at', 'updated_at'])
                break
            except IntegrityError as exc:
                if 'property_join_code_unique' not in str(exc):
                    raise
        else:
            raise RuntimeError('Could not allocate a unique property join code.')
        audit_log.record(
            action='property.join_code_rotated', actor=actor, tenant_id=prop.tenant_id, obj=prop, request=request,
        )
    return prop
