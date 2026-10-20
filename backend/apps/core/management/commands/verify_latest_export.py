"""Verify the newest weekly SQL export (docs/deployment.md, "Weekly export").

Run by the fixed Cloud Run Job `pglive-export-verify` right after the export
Workflow finishes — a fixed job cannot be handed the object name, so it checks
the newest object under EXPORT_PREFIX. "The object exists" is not enough; it must
be a complete, restorable dump:

- non-empty, content type application/gzip, whole gzip stream decompresses;
- starts with the pg_dump header and ends with its completion marker;
- contains at least EXPORT_MIN_TABLES CREATE TABLE statements
  (the job is deployed with `check_db_roles --json` -> table_count).

Exit status 1 (CommandError) fails the Workflow and raises the alert.
"""
import os
import zlib

from django.core.management.base import BaseCommand, CommandError

HEADER = b'-- PostgreSQL database dump'
FOOTER = b'-- PostgreSQL database dump complete'
CREATE_TABLE = b'CREATE TABLE '
CHUNK = 1024 * 1024
HEAD_WINDOW = 512  # pg_dump opens with a comment banner naming itself within the first few lines


def newest_blob(bucket_name, prefix):
    from google.cloud import storage

    blobs = list(storage.Client().list_blobs(bucket_name, prefix=prefix))
    blobs = [b for b in blobs if b.name.endswith('.sql.gz')]
    if not blobs:
        raise CommandError(f'No .sql.gz export under gs://{bucket_name}/{prefix}')
    return max(blobs, key=lambda b: b.time_created)


def inspect_stream(chunks):
    """Decompress a gzip stream chunk by chunk; return (starts_ok, tail, tables, size)."""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    first = b''
    tail = b''
    tables = 0
    size = 0
    carry = b''
    for chunk in chunks:
        data = inflater.decompress(chunk)
        if not data:
            continue
        size += len(data)
        if len(first) < HEAD_WINDOW:
            first += data[:HEAD_WINDOW - len(first)]
        text = carry + data
        tables += text.count(b'\n' + CREATE_TABLE) + (1 if text.startswith(CREATE_TABLE) and not carry else 0)
        carry = text[-len(CREATE_TABLE):]
        tail = (tail + data)[-512:]
    tail += inflater.flush()
    if not inflater.eof:
        raise CommandError('The gzip stream is truncated.')
    return HEADER in first, tail, tables, size


class Command(BaseCommand):
    help = 'Verify the newest SQL export in the backup bucket is a complete, restorable dump.'

    def handle(self, *args, **options):
        bucket = os.environ.get('EXPORT_BUCKET', '')
        prefix = os.environ.get('EXPORT_PREFIX', 'sql/')
        minimum = int(os.environ.get('EXPORT_MIN_TABLES', '1'))
        if not bucket:
            raise CommandError('EXPORT_BUCKET is not set.')

        blob = newest_blob(bucket, prefix)
        if not blob.size:
            raise CommandError(f'{blob.name} is empty.')
        if blob.content_type != 'application/gzip':
            raise CommandError(f'{blob.name} has content type {blob.content_type!r}, expected application/gzip.')

        with blob.open('rb') as handle:
            starts_ok, tail, tables, size = inspect_stream(iter(lambda: handle.read(CHUNK), b''))
        if not starts_ok:
            raise CommandError(f'{blob.name} does not start with the pg_dump header.')
        if FOOTER not in tail:
            raise CommandError(f'{blob.name} is missing the pg_dump completion marker (incomplete dump).')
        if tables < minimum:
            raise CommandError(f'{blob.name} has {tables} CREATE TABLE statements, expected at least {minimum}.')
        self.stdout.write(self.style.SUCCESS(
            f'{blob.name}: {blob.size} bytes gzip, {size} bytes SQL, {tables} tables, complete.'))
