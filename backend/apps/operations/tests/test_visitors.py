from django.urls import reverse
from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import OperationsAPITestCase


def visitor_url(name, visitor, *extra):
    return reverse(f'visitor-{name}', args=[visitor['id'], *extra])


class VisitorCreationTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)

    def _create(self, **overrides):
        payload = {
            'resident': str(self.resident.id), 'visitor_name': 'Ramesh Kumar',
            'mobile_number': '9000000099', 'purpose': 'Family visit',
        }
        payload.update(overrides)
        return self.client.post(reverse('visitor-list'), payload)

    def test_create_defaults_entry_time_to_now_and_is_checked_in(self):
        response = self._create()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNotNone(response.data['entry_time'])
        self.assertIsNone(response.data['exit_time'])
        self.assertTrue(response.data['is_checked_in'])
        self.assertEqual(str(response.data['logged_by']), str(self.owner.id))

    def test_create_honours_explicit_entry_time(self):
        response = self._create(entry_time='2026-07-01T10:00:00Z')
        self.assertEqual(parse_datetime(response.data['entry_time']), parse_datetime('2026-07-01T10:00:00Z'))

    def test_cannot_create_for_resident_in_unassigned_property(self):
        manager = self.create_manager(self.tenant)  # not assigned to self.property
        self.authenticate(manager)

        response = self._create()
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_create_is_audit_logged(self):
        self._create()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='visitor.logged').exists())

    def test_receptionist_can_log_a_visitor(self):
        # manage_visitors is the one permission in the matrix that includes
        # Receptionist — front-desk logging is their primary job.
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self._create()
        self.assertEqual(response.status_code, 201, response.data)


class VisitorCheckOutTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.visitor = self.client.post(reverse('visitor-list'), {
            'resident': str(self.resident.id), 'visitor_name': 'Ramesh Kumar',
            'mobile_number': '9000000099', 'purpose': 'Family visit',
            'entry_time': '2026-07-01T10:00:00Z',
        }).data

    def test_check_out_sets_exit_time_and_actor(self):
        response = self.client.post(visitor_url('check-out', self.visitor), {'exit_time': '2026-07-01T12:00:00Z'})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(parse_datetime(response.data['exit_time']), parse_datetime('2026-07-01T12:00:00Z'))
        self.assertFalse(response.data['is_checked_in'])
        self.assertEqual(str(response.data['checked_out_by']), str(self.owner.id))

    def test_check_out_defaults_to_now_when_omitted(self):
        response = self.client.post(visitor_url('check-out', self.visitor))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNotNone(response.data['exit_time'])

    def test_exit_time_before_entry_time_is_rejected(self):
        response = self.client.post(visitor_url('check-out', self.visitor), {'exit_time': '2026-07-01T09:00:00Z'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('exit_time', response.data)

    def test_cannot_check_out_twice(self):
        self.client.post(visitor_url('check-out', self.visitor), {'exit_time': '2026-07-01T12:00:00Z'})
        response = self.client.post(visitor_url('check-out', self.visitor), {'exit_time': '2026-07-01T13:00:00Z'})
        self.assertEqual(response.status_code, 400)

    def test_check_out_is_audit_logged(self):
        self.client.post(visitor_url('check-out', self.visitor), {'exit_time': '2026-07-01T12:00:00Z'})
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='visitor.checked_out').exists())


class VisitorConfirmTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.visitor = self.client.post(reverse('visitor-list'), {
            'resident': str(self.resident.id), 'visitor_name': 'Ramesh Kumar',
            'mobile_number': '9000000099', 'purpose': 'Family visit',
            'entry_time': '2026-07-01T10:00:00Z',
        }).data

    def test_confirm_stamps_approver(self):
        response = self.client.post(visitor_url('confirm', self.visitor))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(str(response.data['approved_by']), str(self.owner.id))

    def test_cannot_confirm_twice(self):
        self.client.post(visitor_url('confirm', self.visitor))
        response = self.client.post(visitor_url('confirm', self.visitor))
        self.assertEqual(response.status_code, 400)

    def test_confirm_is_audit_logged(self):
        self.client.post(visitor_url('confirm', self.visitor))
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='visitor.confirmed').exists())


class VisitorScopingTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.visitor = self.client.post(reverse('visitor-list'), {
            'resident': str(self.resident.id), 'visitor_name': 'Ramesh Kumar',
            'mobile_number': '9000000099', 'purpose': 'Family visit',
        }).data

    def test_history_is_filterable_by_resident(self):
        other_resident = self.create_resident(self.property, phone='9000000002')
        self.client.post(reverse('visitor-list'), {
            'resident': str(other_resident.id), 'visitor_name': 'Someone Else',
            'mobile_number': '9000000098', 'purpose': 'Delivery',
        })

        response = self.client.get(reverse('visitor-list'), {'resident': str(self.resident.id)})
        ids = [v['id'] for v in response.data]
        self.assertEqual(ids, [self.visitor['id']])

    def test_manager_scoped_to_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_resident = self.create_resident(other_property, phone='9000000002')
        other_visitor = self.client.post(reverse('visitor-list'), {
            'resident': str(other_resident.id), 'visitor_name': 'Someone Else',
            'mobile_number': '9000000098', 'purpose': 'Delivery',
        }).data

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.get(reverse('visitor-list'))
        ids = [v['id'] for v in response.data]
        self.assertIn(self.visitor['id'], ids)
        self.assertNotIn(other_visitor['id'], ids)

    def test_visitor_detail_is_tenant_scoped(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(reverse('visitor-detail', args=[self.visitor['id']]))
        self.assertEqual(response.status_code, 404)
