"""One-line JSON log records for Cloud Logging (prod).

Cloud Logging parses JSON written to stdout: `severity` sets the level and
`message` the summary. Values that look like Aadhaar/PAN numbers, phone
numbers, emails or bearer tokens are masked before the line is written, so a
stray `logger.info(serializer.data)` can't leak them into log storage.
"""
import json
import logging
import re

_MASKS = (
    (re.compile(r'(?i)bearer\s+[a-z0-9._~+/=-]+'), 'Bearer [redacted]'),
    (re.compile(r'\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'), '[jwt]'),
    (re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b'), '[aadhaar]'),
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), '[pan]'),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '[email]'),
    (re.compile(r'(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)'), '[phone]'),
)

_APP_FIELDS = ('app_platform', 'app_version', 'app_build', 'app_flavor', 'app_installation_id')


def scrub(text):
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


class CloudLoggingFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            'severity': record.levelname,
            'message': scrub(record.getMessage()),
            'logger': record.name,
            'time': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
        }
        app = {field: getattr(record, field) for field in _APP_FIELDS
               if getattr(record, field, '-') not in (None, '-')}
        if app:
            entry['app'] = app
        if record.exc_info:
            entry['stack_trace'] = scrub(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)
