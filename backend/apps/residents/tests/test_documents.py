import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from .base import ResidentAPITestCase

_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class ResidentDocumentUploadTests(ResidentAPITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)

    def test_owner_uploads_aadhaar_document_on_create(self):
        self.authenticate(self.owner)
        aadhaar_file = SimpleUploadedFile('aadhaar.pdf', b'%PDF-1.4 fake content', content_type='application/pdf')

        response = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
            'aadhaar_number': '1234-5678-9012', 'aadhaar_document': aadhaar_file,
        }, format='multipart')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('aadhaar.pdf', response.data['aadhaar_document'])

    def test_document_field_is_optional(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
        })

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['aadhaar_document'])
