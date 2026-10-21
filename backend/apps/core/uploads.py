"""Validation for user-uploaded documents: size, and the real file type from its
magic bytes (the client-sent Content-Type and filename are not trusted)."""
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

# Magic-byte sniffing.
_SIGNATURES = (
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'%PDF-', 'application/pdf'),
)


def sniff_upload(upload, *, field, max_bytes, code_prefix):
    """Check an uploaded file's size and real type; return the detected content
    type. Raises a field-keyed DRF ValidationError with the codes
    `<code_prefix>_too_large` / `<code_prefix>_type_not_allowed`."""
    if upload.size > max_bytes:
        raise ValidationError(
            {field: [_('The file is larger than %(mb)s MB.') % {'mb': max_bytes // (1024 * 1024)}]},
            code=f'{code_prefix}_too_large',
        )
    head = upload.read(16)
    upload.seek(0)
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    raise ValidationError(
        {field: [_('Attach a JPEG, PNG, WebP or PDF file.')]},
        code=f'{code_prefix}_type_not_allowed',
    )
