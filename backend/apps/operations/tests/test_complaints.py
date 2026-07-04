from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import OperationsAPITestCase


def complaint_url(name, complaint, *extra):
    return reverse(f'complaint-{name}', args=[complaint['id'], *extra])


class ComplaintCreationTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)

    def _create(self, **overrides):
        payload = {
            'resident': str(self.resident.id), 'category': 'electrical',
            'description': 'Fan not working in room 101.',
        }
        payload.update(overrides)
        return self.client.post(reverse('complaint-list'), payload)

    def test_create_defaults_to_open_medium_priority(self):
        response = self._create()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'open')
        self.assertEqual(response.data['priority'], 'medium')
        self.assertEqual(str(response.data['raised_by']), str(self.owner.id))

    def test_create_honours_explicit_priority(self):
        response = self._create(priority='urgent')
        self.assertEqual(response.data['priority'], 'urgent')

    def test_cannot_create_for_resident_in_unassigned_property(self):
        manager = self.create_manager(self.tenant)  # not assigned to self.property
        self.authenticate(manager)

        response = self._create()
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_create_is_audit_logged(self):
        self._create()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='complaint.created').exists())

    def test_receptionist_cannot_create_complaint(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self._create()
        self.assertEqual(response.status_code, 403)


class ComplaintEditTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.complaint = self.client.post(reverse('complaint-list'), {
            'resident': str(self.resident.id), 'category': 'electrical', 'description': 'Fan broken.',
        }).data

    def test_can_edit_while_open(self):
        response = self.client.patch(
            reverse('complaint-detail', args=[self.complaint['id']]),
            {'priority': 'high', 'description': 'Fan broken and sparking.'},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['priority'], 'high')
        self.assertEqual(response.data['description'], 'Fan broken and sparking.')

    def test_cannot_edit_once_assigned(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.client.post(complaint_url('assign', self.complaint), {'assigned_to': str(manager.id)})

        response = self.client.patch(
            reverse('complaint-detail', args=[self.complaint['id']]), {'priority': 'high'}
        )
        self.assertEqual(response.status_code, 400)

    def test_edit_is_audit_logged(self):
        self.client.patch(reverse('complaint-detail', args=[self.complaint['id']]), {'priority': 'high'})
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='complaint.updated').exists())


class ComplaintAssignmentTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.manager = self.create_manager(self.tenant)
        self.assign_staff(self.manager, self.property)
        self.authenticate(self.owner)
        self.complaint = self.client.post(reverse('complaint-list'), {
            'resident': str(self.resident.id), 'category': 'plumbing', 'description': 'Leaky tap.',
        }).data

    def _assign(self, assignee):
        return self.client.post(complaint_url('assign', self.complaint), {'assigned_to': str(assignee.id)})

    def test_assign_moves_to_assigned_and_stamps_assignee(self):
        response = self._assign(self.manager)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'assigned')
        self.assertEqual(str(response.data['assigned_to']), str(self.manager.id))

    def test_cannot_assign_twice(self):
        self._assign(self.manager)
        response = self._assign(self.manager)
        self.assertEqual(response.status_code, 400)

    def test_cannot_assign_to_a_user_without_complaint_permission(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)

        response = self._assign(receptionist)
        self.assertEqual(response.status_code, 400)
        self.assertIn('assigned_to', response.data)

    def test_cannot_assign_to_a_manager_not_assigned_to_the_property(self):
        other_manager = self.create_manager(self.tenant, email='other-manager@example.com')
        response = self._assign(other_manager)
        self.assertEqual(response.status_code, 400)
        self.assertIn('assigned_to', response.data)

    def test_cannot_assign_to_a_user_in_another_tenant(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')

        response = self._assign(other_owner)
        self.assertEqual(response.status_code, 400)
        self.assertIn('assigned_to', response.data)

    def test_assign_is_audit_logged(self):
        self._assign(self.manager)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='complaint.assigned').exists())


class ComplaintStatusTransitionTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.complaint = self.client.post(reverse('complaint-list'), {
            'resident': str(self.resident.id), 'category': 'security', 'description': 'Gate lock broken.',
        }).data
        self.client.post(complaint_url('assign', self.complaint), {'assigned_to': str(self.owner.id)})

    def _set_status(self, value):
        return self.client.patch(complaint_url('status', self.complaint), {'status': value})

    def test_full_happy_path_lifecycle(self):
        for target in ['in_progress', 'resolved', 'closed']:
            response = self._set_status(target)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['status'], target)

    def test_cannot_skip_from_assigned_to_resolved(self):
        response = self._set_status('resolved')
        self.assertEqual(response.status_code, 400)

    def test_cannot_use_status_endpoint_to_reach_assigned(self):
        response = self._set_status('assigned')
        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.data)

    def test_closed_is_terminal(self):
        self._set_status('in_progress')
        self._set_status('resolved')
        self._set_status('closed')

        response = self._set_status('in_progress')
        self.assertEqual(response.status_code, 400)

    def test_status_change_is_audit_logged(self):
        self._set_status('in_progress')
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='complaint.status_changed').exists())


class ComplaintCommentTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.complaint = self.client.post(reverse('complaint-list'), {
            'resident': str(self.resident.id), 'category': 'other', 'description': 'Noise complaint.',
        }).data

    def test_comments_list_starts_empty(self):
        response = self.client.get(complaint_url('comments', self.complaint))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_posting_a_comment_stamps_author(self):
        response = self.client.post(complaint_url('comments', self.complaint), {'body': 'Looking into it.'})

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['body'], 'Looking into it.')
        self.assertEqual(str(response.data['author']), str(self.owner.id))

    def test_comments_appear_in_order_on_the_complaint(self):
        self.client.post(complaint_url('comments', self.complaint), {'body': 'First.'})
        self.client.post(complaint_url('comments', self.complaint), {'body': 'Second.'})

        detail = self.client.get(reverse('complaint-detail', args=[self.complaint['id']]))
        bodies = [c['body'] for c in detail.data['comments']]
        self.assertEqual(bodies, ['First.', 'Second.'])

    def test_comment_is_audit_logged(self):
        self.client.post(complaint_url('comments', self.complaint), {'body': 'Noted.'})
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='complaint.comment_added').exists())


class ComplaintScopingTests(OperationsAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        self.complaint = self.client.post(reverse('complaint-list'), {
            'resident': str(self.resident.id), 'category': 'other', 'description': 'Test complaint.',
        }).data

    def test_manager_scoped_to_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_resident = self.create_resident(other_property, phone='9000000002')
        other_complaint = self.client.post(reverse('complaint-list'), {
            'resident': str(other_resident.id), 'category': 'other', 'description': 'Other.',
        }).data

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.get(reverse('complaint-list'))
        ids = [c['id'] for c in response.data]
        self.assertIn(self.complaint['id'], ids)
        self.assertNotIn(other_complaint['id'], ids)

    def test_complaint_detail_is_tenant_scoped(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(reverse('complaint-detail', args=[self.complaint['id']]))
        self.assertEqual(response.status_code, 404)

    def test_receptionist_cannot_view_complaints(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self.client.get(reverse('complaint-list'))
        self.assertEqual(response.status_code, 403)
