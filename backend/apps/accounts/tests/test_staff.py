from django.core import mail
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase


def staff_payload(**overrides):
    payload = {
        'email': 'suresh@example.com',
        'first_name': 'Suresh',
        'role': Role.MANAGER,
    }
    payload.update(overrides)
    return payload


class StaffManagementTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_owner_creates_manager_with_invite_and_audit_log(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('staff-list'), staff_payload())

        self.assertEqual(response.status_code, 201)
        manager = User.objects.get(email='suresh@example.com')
        self.assertEqual(manager.tenant, self.tenant)
        self.assertEqual(manager.role, Role.MANAGER)
        self.assertFalse(manager.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)  # invite with set-password link
        with tenant_context(self.tenant.id):
            self.assertTrue(
                AuditLog.objects.filter(action='staff.created', object_id=str(manager.id)).exists()
            )

    def test_invite_flow_lets_staff_set_password_and_log_in(self):
        self.authenticate(self.owner)
        self.client.post(reverse('staff-list'), staff_payload())
        body = mail.outbox[0].body

        self.client.credentials()  # drop owner auth
        confirm = self.client.post(
            reverse('auth-password-reset-confirm'),
            {
                'uid': self.extract_query_param(body, 'uid'),
                'token': self.extract_query_param(body, 'token'),
                'new_password': 'Quiet-Harbor-19',
            },
        )
        self.assertEqual(confirm.status_code, 200)

        login = self.client.post(
            reverse('auth-login'),
            {'email': 'suresh@example.com', 'password': 'Quiet-Harbor-19'},
        )
        self.assertEqual(login.status_code, 200)

    def test_staff_role_must_be_manager_or_receptionist(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('staff-list'), staff_payload(role=Role.OWNER))
        self.assertEqual(response.status_code, 400)

    def test_manager_cannot_manage_staff_accounts(self):
        manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')
        self.authenticate(manager)
        self.assertEqual(self.client.get(reverse('staff-list')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('staff-list'), staff_payload()).status_code, 403
        )

    def test_receptionist_and_resident_cannot_manage_staff(self):
        for role, email in [
            (Role.RECEPTIONIST, 'reception@example.com'),
            (Role.RESIDENT, 'resident@example.com'),
        ]:
            user = self.create_user(self.tenant, role, email)
            self.authenticate(user)
            self.assertEqual(self.client.get(reverse('staff-list')).status_code, 403)

    def test_staff_list_is_tenant_scoped(self):
        # Module isolation test (invariant 1, app-level: users sit outside RLS).
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other@example.com')
        self.create_user(other_tenant, Role.MANAGER, 'other-manager@example.com')
        mine = self.create_user(self.tenant, Role.MANAGER, 'my-manager@example.com')

        self.authenticate(self.owner)
        response = self.client.get(reverse('staff-list'))
        emails = {row['email'] for row in response.data}
        self.assertEqual(emails, {'my-manager@example.com'})

        detail = self.client.get(reverse('staff-detail', args=[mine.id]))
        self.assertEqual(detail.status_code, 200)

        self.authenticate(other_owner)
        cross = self.client.get(reverse('staff-detail', args=[mine.id]))
        self.assertEqual(cross.status_code, 404)

    def test_role_change_writes_audit_log_with_before_after(self):
        manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')
        self.authenticate(self.owner)

        response = self.client.patch(
            reverse('staff-detail', args=[manager.id]), {'role': Role.RECEPTIONIST}
        )

        self.assertEqual(response.status_code, 200)
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='staff.updated', object_id=str(manager.id))
        self.assertEqual(entry.before['role'], Role.MANAGER)
        self.assertEqual(entry.after['role'], Role.RECEPTIONIST)

    def test_deactivated_staff_cannot_log_in(self):
        manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')
        self.authenticate(self.owner)
        self.client.patch(reverse('staff-detail', args=[manager.id]), {'is_active': False})

        self.client.credentials()
        login = self.client.post(
            reverse('auth-login'),
            {'email': 'manager@example.com', 'password': STRONG_PASSWORD},
        )
        self.assertEqual(login.status_code, 401)
