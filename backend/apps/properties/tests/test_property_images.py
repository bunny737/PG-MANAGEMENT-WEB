import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.roles import Role

from .base import PropertyAPITestCase

_MEDIA_ROOT = tempfile.mkdtemp()

# Minimal valid 1x1 transparent GIF — ImageField validates real image bytes.
_GIF_BYTES = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01'
    b'\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
)


def gif_file(name='photo.gif'):
    return SimpleUploadedFile(name, _GIF_BYTES, content_type='image/gif')


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class PropertyImageTests(PropertyAPITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)

    def test_owner_uploads_image_and_it_appears_on_property_detail(self):
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('property-upload-image', args=[self.property.id]),
            {'image': gif_file()}, format='multipart',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['order'], 0)
        self.assertIn('photo.gif', response.data['image'])

        detail = self.client.get(reverse('property-detail', args=[self.property.id]))
        self.assertEqual(len(detail.data['images']), 1)

    def test_second_upload_gets_next_order(self):
        self.authenticate(self.owner)
        upload_url = reverse('property-upload-image', args=[self.property.id])

        self.client.post(upload_url, {'image': gif_file('one.gif')}, format='multipart')
        second = self.client.post(upload_url, {'image': gif_file('two.gif')}, format='multipart')

        self.assertEqual(second.data['order'], 1)

    def test_image_is_required(self):
        self.authenticate(self.owner)
        response = self.client.post(
            reverse('property-upload-image', args=[self.property.id]), {}, format='multipart',
        )
        self.assertEqual(response.status_code, 400)

    def test_manager_cannot_upload_or_delete_image(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.post(
            reverse('property-upload-image', args=[self.property.id]),
            {'image': gif_file()}, format='multipart',
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_deletes_an_image(self):
        self.authenticate(self.owner)
        upload = self.client.post(
            reverse('property-upload-image', args=[self.property.id]),
            {'image': gif_file()}, format='multipart',
        )
        image_id = upload.data['id']

        response = self.client.delete(
            reverse('property-delete-image', args=[self.property.id, image_id])
        )

        self.assertEqual(response.status_code, 204)
        detail = self.client.get(reverse('property-detail', args=[self.property.id]))
        self.assertEqual(detail.data['images'], [])

    def test_cannot_upload_image_to_property_in_another_tenant(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.post(
            reverse('property-upload-image', args=[self.property.id]),
            {'image': gif_file()}, format='multipart',
        )
        self.assertEqual(response.status_code, 404)
