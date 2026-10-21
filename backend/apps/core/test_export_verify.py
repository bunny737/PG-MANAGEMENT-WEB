"""pglive-export-verify: a SQL export is only a backup if it is complete and restorable."""
import gzip
import io
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .management.commands import verify_latest_export as command

BODY = (
    b'--\n-- PostgreSQL database dump\n--\n\nSET statement_timeout = 0;\n'
    + b''.join(b'\nCREATE TABLE public.t%d (id integer);\n' % n for n in range(3))
    + b'\n--\n-- PostgreSQL database dump complete\n--\n'
)


class FakeBlob:
    def __init__(self, data, name='sql/pg_platform-20261021-000000Z.sql.gz', content_type='application/gzip',
                 time_created=1):
        self.data, self.name, self.content_type, self.time_created = data, name, content_type, time_created
        self.size = len(data)

    def open(self, mode):
        return io.BytesIO(self.data)


def run(blobs, minimum='3', **env):
    env = {'EXPORT_BUCKET': 'backups', 'EXPORT_MIN_TABLES': minimum, **env}
    with mock.patch.dict('os.environ', env), \
         mock.patch.object(command, 'newest_blob', side_effect=lambda *a: max(blobs, key=lambda b: b.time_created)):
        out = io.StringIO()
        call_command('verify_latest_export', stdout=out)
        return out.getvalue()


class VerifyLatestExportTests(SimpleTestCase):
    def test_complete_dump_passes(self):
        self.assertIn('3 tables, complete', run([FakeBlob(gzip.compress(BODY))]))

    def test_dump_larger_than_one_read_chunk_still_counts_every_table(self):
        big = BODY.replace(b'SET statement_timeout = 0;', b'-- ' + b'x' * (3 * 1024 * 1024))
        with mock.patch.object(command, 'CHUNK', 64 * 1024):
            self.assertIn('3 tables, complete', run([FakeBlob(gzip.compress(big))]))

    def assertFails(self, blob, fragment, **kwargs):
        with self.assertRaises(CommandError) as ctx:
            run([blob], **kwargs)
        self.assertIn(fragment, str(ctx.exception))

    def test_truncated_gzip_fails(self):
        self.assertFails(FakeBlob(gzip.compress(BODY)[:-20]), 'truncated')

    def test_not_gzip_fails(self):
        with self.assertRaises(Exception):
            run([FakeBlob(BODY)])

    def test_missing_completion_marker_fails(self):
        self.assertFails(FakeBlob(gzip.compress(BODY.replace(b'dump complete', b'dump'))), 'completion marker')

    def test_wrong_header_fails(self):
        # A real dump is far longer than the head window, so the completion marker is not in it.
        padding = b'-- ' + b'x' * 600 + b'\n'
        other = b'--\n-- some other tool\n' + padding + BODY.split(b'SET statement_timeout')[1]
        self.assertFails(FakeBlob(gzip.compress(other)), 'header')

    def test_too_few_tables_fails(self):
        self.assertFails(FakeBlob(gzip.compress(BODY)), 'expected at least 70', minimum='70')

    def test_empty_object_and_wrong_content_type_fail(self):
        self.assertFails(FakeBlob(b''), 'empty')
        self.assertFails(FakeBlob(gzip.compress(BODY), content_type='application/octet-stream'), 'content type')

    def test_only_the_newest_export_is_checked(self):
        good = FakeBlob(gzip.compress(BODY), time_created=2)
        broken = FakeBlob(b'x', name='sql/old.sql.gz', time_created=1)
        self.assertIn('complete', run([broken, good]))

    def test_requires_a_bucket(self):
        with mock.patch.dict('os.environ', {'EXPORT_BUCKET': ''}), self.assertRaises(CommandError):
            call_command('verify_latest_export', stdout=io.StringIO())
