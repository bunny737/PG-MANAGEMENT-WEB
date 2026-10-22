from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.core.uploads import sniff_upload

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 20
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20
PDF = b'%PDF-1.7 ' + b'0' * 20
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'0' * 20


def upload(content, name='file.bin'):
    return SimpleUploadedFile(name, content)


def sniff(content, **overrides):
    options = {'field': 'document', 'max_bytes': 1024, 'code_prefix': 'doc'} | overrides
    return sniff_upload(upload(content), **options)


class SniffUploadTests(SimpleTestCase):
    def test_detects_each_allowed_type_from_its_bytes(self):
        self.assertEqual(sniff(JPEG), 'image/jpeg')
        self.assertEqual(sniff(PNG), 'image/png')
        self.assertEqual(sniff(PDF), 'application/pdf')
        self.assertEqual(sniff(WEBP), 'image/webp')

    def test_the_filename_and_client_type_are_not_trusted(self):
        fake = SimpleUploadedFile('scan.pdf', b'MZ\x90\x00 an executable', content_type='application/pdf')
        with self.assertRaises(ValidationError) as caught:
            sniff_upload(fake, field='document', max_bytes=1024, code_prefix='doc')
        self.assertEqual(caught.exception.detail['document'][0].code, 'doc_type_not_allowed')

    def test_a_riff_file_that_is_not_webp_is_rejected(self):
        with self.assertRaises(ValidationError):
            sniff(b'RIFF\x00\x00\x00\x00WAVEfmt ' + b'0' * 20)

    def test_too_large_reports_the_limit_in_megabytes(self):
        with self.assertRaises(ValidationError) as caught:
            sniff(PDF + b'0' * (5 * 1024 * 1024), max_bytes=5 * 1024 * 1024)
        error = caught.exception.detail['document'][0]
        self.assertEqual(error.code, 'doc_too_large')
        self.assertIn('5 MB', str(error))

    def test_size_is_checked_before_the_type(self):
        with self.assertRaises(ValidationError) as caught:
            sniff(b'MZ' + b'0' * 2000)
        self.assertEqual(caught.exception.detail['document'][0].code, 'doc_too_large')

    def test_a_file_exactly_at_the_limit_passes(self):
        self.assertEqual(sniff(PDF + b'0' * (1024 - len(PDF)), max_bytes=1024), 'application/pdf')

    def test_the_stream_is_rewound_for_the_caller(self):
        file = upload(PDF)
        sniff_upload(file, field='document', max_bytes=1024, code_prefix='doc')
        self.assertEqual(file.read(5), b'%PDF-')

    def test_errors_are_keyed_by_the_given_field(self):
        with self.assertRaises(ValidationError) as caught:
            sniff_upload(upload(b'nope'), field='pan_document', max_bytes=1024, code_prefix='kyc')
        self.assertEqual(list(caught.exception.detail), ['pan_document'])

    def test_allowed_types_restricts_what_a_caller_accepts(self):
        restricted = {'allowed_types': {'image/jpeg', 'image/png', 'application/pdf'}}
        self.assertEqual(sniff(PDF, **restricted), 'application/pdf')
        with self.assertRaises(ValidationError) as caught:
            sniff(WEBP, **restricted)
        error = caught.exception.detail['document'][0]
        self.assertEqual(error.code, 'doc_type_not_allowed')
        self.assertNotIn('WebP', str(error))
