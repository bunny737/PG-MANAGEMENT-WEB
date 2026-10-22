"""Validation for user-uploaded documents: size, and the real file type from its
magic bytes (the client-sent Content-Type and filename are not trusted)."""
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

# Magic-byte sniffing. WebP needs its own check (RIFF container + a WEBP tag at offset 8),
# not a fixed prefix, so it isn't in this table.
_SIGNATURES = (
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'%PDF-', 'application/pdf'),
)
_WEBP_CONTENT_TYPE = 'image/webp'
ALL_TYPES = frozenset({'image/jpeg', 'image/png', 'application/pdf', _WEBP_CONTENT_TYPE})


def _detect(upload):
    head = upload.read(16)
    upload.seek(0)
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return _WEBP_CONTENT_TYPE
    return None


def sniff_upload(upload, *, field, max_bytes, code_prefix, allowed_types=ALL_TYPES):
    """Check an uploaded file's size and real type against `allowed_types` (default: every type
    this module can detect); return the detected content type. Raises a field-keyed DRF
    ValidationError with the codes `<code_prefix>_too_large` / `<code_prefix>_type_not_allowed`."""
    if upload.size > max_bytes:
        raise ValidationError(
            {field: [_('The file is larger than %(mb)s MB.') % {'mb': max_bytes // (1024 * 1024)}]},
            code=f'{code_prefix}_too_large',
        )
    detected = _detect(upload)
    if detected is None or detected not in allowed_types:
        # Two fixed, translated messages rather than a list built from `allowed_types` at runtime,
        # so this doesn't need a new catalogue entry for every combination a future caller might pass.
        message = (
            _('Attach a JPEG, PNG, WebP or PDF file.') if _WEBP_CONTENT_TYPE in allowed_types
            else _('Attach a JPEG, PNG or PDF file.')
        )
        raise ValidationError({field: [message]}, code=f'{code_prefix}_type_not_allowed')
    return detected
