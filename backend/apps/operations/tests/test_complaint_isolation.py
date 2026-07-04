"""Tenant-isolation proof for complaints + comments (invariant 1)."""
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.operations.models import Complaint, ComplaintComment

from .base import OperationsAPITestCase


class ComplaintRowLevelSecurityTests(TestCase):
    @staticmethod
    def _complaint(tenant, phone):
        prop = OperationsAPITestCase.create_property(tenant, name=f'Prop {phone}')
        resident = OperationsAPITestCase.create_resident(prop, phone=phone)
        with tenant_context(tenant.id):
            complaint = Complaint.objects.create(
                tenant_id=tenant.id, resident=resident, category='electrical',
                description='Test complaint',
            )
            ComplaintComment.objects.create(
                tenant_id=tenant.id, complaint=complaint, body='Test comment',
            )
            return complaint

    def setUp(self):
        self.tenant_a = OperationsAPITestCase.create_tenant('Tenant A')
        self.tenant_b = OperationsAPITestCase.create_tenant('Tenant B')
        self.complaint_a = self._complaint(self.tenant_a, '9000000001')
        self._complaint(self.tenant_b, '9000000002')

    def test_tenant_context_sees_only_own_complaints(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Complaint.objects.count(), 1)
            self.assertEqual(ComplaintComment.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertEqual(ComplaintComment.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Complaint.objects.count(), 2)
            self.assertEqual(ComplaintComment.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    ComplaintComment.objects.create(
                        tenant_id=self.tenant_b.id, complaint=self.complaint_a, body='Evil',
                    )
