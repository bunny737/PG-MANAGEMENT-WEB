import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import ResidentAPITestCase

_MEDIA_ROOT = tempfile.mkdtemp()

PDF = b'%PDF-1.4 ' + b'0' * 32
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
JPEG = b'\xff\xd8\xff\xe0' + b'0' * 32
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'0' * 32
EXECUTABLE = b'MZ\x90\x00 not a document'


class KycTestCase(ResidentAPITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.authenticate(self.owner)

    def payload(self, **files):
        return {'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001', **files}

    def create(self, **files):
        return self.client.post(reverse('resident-list'), self.payload(**files), format='multipart')

    def patch(self, resident_id, data, format='multipart'):
        return self.client.patch(reverse('resident-detail', args=[resident_id]), data, format=format)

    @staticmethod
    def doc(name, content):
        return SimpleUploadedFile(name, content)

    def resident_count(self):
        with tenant_context(self.tenant.id):
            return Resident.objects.count()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, KYC_UPLOADS_ENABLED=True, KYC_DOCUMENT_MAX_BYTES=1024)
class KycUploadsEnabledTests(KycTestCase):
    def test_accepts_pdf_jpeg_and_png(self):
        for index, (name, content) in enumerate(
            [('a.pdf', PDF), ('a.jpg', JPEG), ('a.png', PNG)]
        ):
            response = self.client.post(
                reverse('resident-list'),
                self.payload(first_name=f'R{index}', phone=f'90000000{index:02d}',
                             aadhaar_document=self.doc(name, content), pan_document=self.doc(name, content)),
                format='multipart',
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertTrue(response.data['aadhaar_document'])
            self.assertTrue(response.data['pan_document'])

    def test_webp_is_not_in_the_approved_kyc_set(self):
        # apps.core.uploads also backs expenses, which does accept WebP — KYC passes its own
        # narrower allowed_types, since only PDF/JPEG/PNG were approved for identity documents.
        response = self.create(aadhaar_document=self.doc('a.webp', WEBP))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['aadhaar_document'][0].code, 'document_type_not_allowed')

    def test_clearing_a_document_deletes_the_stored_file(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, name = stored.storage, stored.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            cleared = self.patch(created.data['id'], {'aadhaar_document': None}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertFalse(storage.exists(name))

    def test_replacing_a_document_deletes_the_old_file_only_after_commit(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, first = stored.storage, stored.name
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            replaced = self.patch(created.data['id'], {'aadhaar_document': self.doc('b.pdf', PDF)})
        self.assertEqual(replaced.status_code, 200, replaced.data)
        self.assertTrue(storage.exists(first))  # nothing is deleted before the commit
        for callback in callbacks:
            callback()
        self.assertFalse(storage.exists(first))
        with tenant_context(self.tenant.id):
            second = Resident.objects.get(pk=created.data['id']).aadhaar_document.name
        self.assertTrue(storage.exists(second))

    def test_an_invalid_replacement_does_not_delete_the_existing_file(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, name = stored.storage, stored.name
        with self.captureOnCommitCallbacks(execute=True):
            bad = self.patch(created.data['id'], {'aadhaar_document': self.doc('x.pdf', EXECUTABLE)})
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(storage.exists(name))

    def test_the_real_type_is_checked_not_the_filename(self):
        for field in ('aadhaar_document', 'pan_document'):
            response = self.create(**{field: self.doc('scan.pdf', EXECUTABLE)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data[field][0].code, 'document_type_not_allowed')
        self.assertEqual(self.resident_count(), 0)

    def test_oversized_files_are_rejected(self):
        response = self.create(aadhaar_document=self.doc('big.pdf', PDF + b'0' * 2048))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['aadhaar_document'][0].code, 'document_too_large')

    def test_a_replacement_is_validated_and_a_bad_one_keeps_the_stored_file(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        before = created.data['aadhaar_document']
        bad = self.patch(created.data['id'], {'aadhaar_document': self.doc('x.pdf', EXECUTABLE)})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.get(reverse('resident-detail', args=[created.data['id']])).data['aadhaar_document'], before)

    def test_a_resident_of_another_tenant_cannot_be_touched(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.authenticate(other)
        response = self.patch(created.data['id'], {'pan_document': self.doc('p.pdf', PDF)})
        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, KYC_UPLOADS_ENABLED=False)
class KycUploadsDisabledTests(KycTestCase):
    def test_a_new_document_is_refused_on_create_and_nothing_is_created(self):
        for field in ('aadhaar_document', 'pan_document'):
            response = self.create(**{field: self.doc('a.pdf', PDF)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data[field][0].code, 'kyc_uploads_disabled')
        self.assertEqual(self.resident_count(), 0)

    def test_creating_a_resident_without_documents_still_works(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['aadhaar_document'])

    def test_a_new_document_is_refused_on_update_even_with_a_valid_file(self):
        resident = self.create().data
        response = self.patch(resident['id'], {'pan_document': self.doc('p.pdf', PDF)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['pan_document'][0].code, 'kyc_uploads_disabled')
        self.assertIsNone(self.client.get(reverse('resident-detail', args=[resident['id']])).data['pan_document'])

    def test_text_fields_can_still_be_edited(self):
        resident = self.create().data
        response = self.patch(resident['id'], {'aadhaar_number': '1234-5678-9012', 'first_name': 'Ravi K'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['first_name'], 'Ravi K')

    def test_stored_documents_stay_readable_and_can_be_cleared(self):
        with override_settings(KYC_UPLOADS_ENABLED=True):
            created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        url = created.data['aadhaar_document']
        self.assertTrue(url)
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, name = stored.storage, stored.name

        detail = reverse('resident-detail', args=[created.data['id']])
        self.assertEqual(self.client.get(detail).data['aadhaar_document'], url)  # still readable

        replacement = self.patch(created.data['id'], {'aadhaar_document': self.doc('b.pdf', PDF)})
        self.assertEqual(replacement.status_code, 400)  # but not replaceable
        self.assertEqual(self.client.get(detail).data['aadhaar_document'], url)
        self.assertTrue(storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            cleared = self.patch(created.data['id'], {'aadhaar_document': None}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertIsNone(cleared.data['aadhaar_document'])
        self.assertFalse(storage.exists(name))  # clearing deletes the file, not just the reference

    def test_a_resident_of_another_tenant_cannot_be_touched(self):
        resident = self.create().data
        other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.authenticate(other)
        self.assertEqual(self.patch(resident['id'], {'pan_document': self.doc('p.pdf', PDF)}).status_code, 404)


class KycFlagOnMeTests(KycTestCase):
    @override_settings(KYC_UPLOADS_ENABLED=False)
    def test_me_reports_uploads_off(self):
        self.assertIs(self.client.get(reverse('auth-me')).data['kyc_uploads_enabled'], False)

    @override_settings(KYC_UPLOADS_ENABLED=True)
    def test_me_reports_uploads_on(self):
        self.assertIs(self.client.get(reverse('auth-me')).data['kyc_uploads_enabled'], True)
