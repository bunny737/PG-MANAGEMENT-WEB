import re


def normalize_email(value: str | None) -> str | None:
    """Normalize an email address: blank/whitespace-only -> None; otherwise strip and lowercase."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.lower()


def normalize_phone(value: str | None) -> str | None:
    """Normalize a phone number: blank/whitespace-only -> None.
    Otherwise strip all non-digit characters, then accept ONLY:
      - exactly 10 digits
      - exactly 11 digits starting with '0' -> drop leading '0'
      - exactly 12 digits starting with '91' -> drop leading '91'
    Then validate against ^[6-9]\\d{9}$.
    Raise generic ValueError on any unsupported shape or validation failure.
    """
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
