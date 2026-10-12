"""Owner-configurable module access: API, audit, tenant isolation, concurrency."""
import threading
import time

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.serializers import LoginSerializer
from apps.accounts.staff_access import locked_staff
from apps.audit.models import AuditLog
from apps.core.modules import FULL, MODULE_KEYS, MODULES, OFF, VIEW, role_default_levels
from apps.core.roles import Role, permissions_for, permissions_for_user
from apps.core.tenancy import tenant_context

from .base import AuthAPITestCase


def levels_for(role, **changes):
    levels = role_default_levels(role)
    levels.update(changes)
    return levels


def url(staff):
    return reverse('staff-module-access', args=[staff.id])


class ModuleAccessAPITests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')
        self.receptionist = self.create_user(self.tenant, Role.RECEPTIONIST, 'desk@example.com')

        self.other_tenant = self.create_tenant('Other PG')
        self.other_owner = self.create_owner(self.other_tenant, email='owner@other.example.com')
        self.other_staff = self.create_user(self.other_tenant, Role.MANAGER, 'mgr@other.example.com')

    def put(self, staff, levels, role=None):
        return self.client.put(
            url(staff), {'role': role or staff.role, 'levels': levels}, format='json'
        )

    def audit_entries(self, staff):
        with tenant_context(self.tenant.id):
            return list(AuditLog.objects.filter(
                action='staff.module_access_updated', object_id=str(staff.id)
            ).order_by('created_at'))

    # --- read -------------------------------------------------------------

    def test_owner_reads_registry_and_role_defaults(self):
        self.authenticate(self.owner)
        response = self.client.get(url(self.receptionist))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['role'], 'receptionist')
        self.assertFalse(response.data['customized'])
        by_key = {m['key']: m for m in response.data['modules']}
        self.assertEqual(list(by_key), list(MODULE_KEYS))
        self.assertEqual(by_key['finance']['levels'], [OFF, VIEW, FULL])
        self.assertEqual(by_key['complaints']['levels'], [OFF, FULL])
        self.assertEqual(by_key['tenants']['level'], VIEW)
        self.assertEqual(by_key['visitors']['level'], FULL)

    def test_staff_cannot_manage_module_access(self):
        for actor in (self.manager, self.receptionist):
            self.authenticate(actor)
            self.assertEqual(self.client.get(url(self.receptionist)).status_code, 403)
            self.assertEqual(self.put(self.receptionist, levels_for(Role.RECEPTIONIST)).status_code, 403)
            self.assertEqual(self.client.delete(url(self.receptionist)).status_code, 403)

    def test_staff_cannot_edit_their_own_access(self):
        self.authenticate(self.manager)
        response = self.put(self.manager, levels_for(Role.MANAGER, finance=OFF))
        self.assertEqual(response.status_code, 403)
        self.manager.refresh_from_db()
        self.assertIsNone(self.manager.module_access)

    def test_unauthenticated_is_rejected(self):
        self.assertEqual(self.client.get(url(self.receptionist)).status_code, 401)

    def test_unknown_staff_and_non_staff_ids_are_404(self):
        self.authenticate(self.owner)
        self.assertEqual(
            self.client.get(reverse('staff-module-access', args=['00000000-0000-0000-0000-000000000000'])).status_code,
            404,
        )
        # The owner themself is not staff.
        self.assertEqual(self.client.get(url(self.owner)).status_code, 404)

    # --- tenant isolation (invariant 1) ----------------------------------

    def test_cross_tenant_staff_is_404_for_every_method(self):
        self.authenticate(self.owner)
        self.assertEqual(self.client.get(url(self.other_staff)).status_code, 404)
        self.assertEqual(self.put(self.other_staff, levels_for(Role.MANAGER, finance=OFF)).status_code, 404)
        self.assertEqual(self.client.delete(url(self.other_staff)).status_code, 404)
        self.other_staff.refresh_from_db()
        self.assertIsNone(self.other_staff.module_access)

    # --- write ------------------------------------------------------------

    def test_put_customizes_audits_and_is_reflected_in_me(self):
        self.authenticate(self.owner)
        levels = levels_for(Role.RECEPTIONIST, finance=VIEW, visitors=OFF)
        response = self.put(self.receptionist, levels)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['customized'])
        self.receptionist.refresh_from_db()
        self.assertEqual(self.receptionist.module_access, {'base_role': 'receptionist', 'levels': levels})

        entry, = self.audit_entries(self.receptionist)
        self.assertEqual(entry.actor_id, self.owner.id)
        self.assertEqual(entry.before['levels']['finance'], OFF)
        self.assertEqual(entry.after['levels']['finance'], VIEW)
        self.assertFalse(entry.before['customized'])
        self.assertTrue(entry.after['customized'])
        self.assertIsNotNone(entry.ip_address)

        # The staff member's own /auth/me/ now reflects it, server-side and immediately.
        self.authenticate(self.receptionist)
        perms = self.client.get(reverse('auth-me')).data['permissions']
        self.assertIn('view_finance', perms)
        self.assertNotIn('manage_visitors', perms)
        self.assertNotIn('manage_invoices', perms)

    def test_put_equal_to_role_defaults_stores_null(self):
        self.authenticate(self.owner)
        self.put(self.manager, levels_for(Role.MANAGER, finance=VIEW))
        response = self.put(self.manager, role_default_levels(Role.MANAGER))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['customized'])
        self.manager.refresh_from_db()
        self.assertIsNone(self.manager.module_access)

    def test_put_is_a_complete_replacement(self):
        self.authenticate(self.owner)
        base = levels_for(Role.MANAGER)

        missing = dict(base)
        del missing['reports']
        unknown = dict(base, mystery=FULL)
        unsupported = dict(base, complaints=VIEW)
        bogus = dict(base, finance='superuser')
        for payload, bad_key in (
            (missing, 'reports'), (unknown, 'mystery'),
            (unsupported, 'complaints'), (bogus, 'finance'),
        ):
            response = self.put(self.manager, payload)
            self.assertEqual(response.status_code, 400, payload)
            self.assertIn(bad_key, response.data['levels'])
        self.manager.refresh_from_db()
        self.assertIsNone(self.manager.module_access)

    def test_put_rejects_bad_body_shapes(self):
        self.authenticate(self.owner)
        for body in (
            {'role': 'manager'},
            {'levels': levels_for(Role.MANAGER)},
            {'role': 'owner', 'levels': levels_for(Role.MANAGER)},
            {'role': 'manager', 'levels': ['finance']},
        ):
            self.assertEqual(self.client.put(url(self.manager), body, format='json').status_code, 400, body)

    def test_role_mismatch_is_409_role_changed(self):
        self.authenticate(self.owner)
        # The client rendered this staff member as a receptionist, but they're a manager.
        response = self.put(self.manager, levels_for(Role.RECEPTIONIST), role=Role.RECEPTIONIST)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'ROLE_CHANGED')
        self.assertTrue(response.data['detail'])
        self.manager.refresh_from_db()
        self.assertIsNone(self.manager.module_access)
        self.assertEqual(self.audit_entries(self.manager), [])

    def test_delete_resets_to_role_defaults_and_audits(self):
        self.authenticate(self.owner)
        self.put(self.manager, levels_for(Role.MANAGER, finance=OFF))
        response = self.client.delete(url(self.manager))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['customized'])
        self.manager.refresh_from_db()
        self.assertIsNone(self.manager.module_access)
        last = self.audit_entries(self.manager)[-1]
        self.assertTrue(last.before['customized'])
        self.assertFalse(last.after['customized'])

    def test_inactive_staff_are_readable_and_editable(self):
        self.manager.is_active = False
        self.manager.save()
        self.authenticate(self.owner)

        self.assertEqual(self.client.get(url(self.manager)).status_code, 200)
        response = self.put(self.manager, levels_for(Role.MANAGER, finance=OFF))
        self.assertEqual(response.status_code, 200)

        # Overrides persist through reactivation.
        self.client.patch(reverse('staff-detail', args=[self.manager.id]), {'is_active': True}, format='json')
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.is_active)
        self.assertEqual(self.manager.module_access['levels']['finance'], OFF)

    def test_module_access_is_not_writable_through_staff_endpoints(self):
        self.authenticate(self.owner)
        payload = {'module_access': {'base_role': 'manager', 'levels': levels_for(Role.MANAGER, finance=OFF)}}
        self.client.patch(reverse('staff-detail', args=[self.manager.id]), payload, format='json')
        self.manager.refresh_from_db()
        self.assertIsNone(self.manager.module_access)

    # --- role changes -------------------------------------------------------

    def test_role_patch_clears_overrides_and_audits_them(self):
        self.authenticate(self.owner)
        self.put(self.manager, levels_for(Role.MANAGER, finance=OFF))

        response = self.client.patch(
            reverse('staff-detail', args=[self.manager.id]), {'role': Role.RECEPTIONIST}, format='json'
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, Role.RECEPTIONIST)
        self.assertIsNone(self.manager.module_access)
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='staff.updated', object_id=str(self.manager.id))
        self.assertIsNotNone(entry.before['module_access'])
        self.assertIsNone(entry.after['module_access'])
        self.assertEqual(entry.before['role'], Role.MANAGER)
        self.assertEqual(entry.after['role'], Role.RECEPTIONIST)

    def test_role_change_outside_the_api_voids_the_override(self):
        """base_role stamping: an admin/shell role edit can't leave a stale override active."""
        self.authenticate(self.owner)
        self.put(self.manager, levels_for(Role.MANAGER, **{m: OFF for m in MODULE_KEYS}))
        self.manager.refresh_from_db()
        self.manager.role = Role.RECEPTIONIST  # bypasses the API on purpose
        self.manager.save(update_fields=['role'])

        self.assertEqual(permissions_for_user(self.manager), permissions_for(Role.RECEPTIONIST))

    def test_patch_without_role_change_keeps_overrides(self):
        self.authenticate(self.owner)
        self.put(self.manager, levels_for(Role.MANAGER, finance=OFF))
        self.client.patch(reverse('staff-detail', args=[self.manager.id]), {'first_name': 'Renamed'}, format='json')
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.first_name, 'Renamed')
        self.assertEqual(self.manager.module_access['levels']['finance'], OFF)

    def test_staff_detail_route_does_not_expose_put_or_delete(self):
        self.authenticate(self.owner)
        detail = reverse('staff-detail', args=[self.manager.id])
        self.assertEqual(self.client.put(detail, {}, format='json').status_code, 405)
        self.assertEqual(self.client.delete(detail).status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.manager.pk).exists())

    def test_permission_reduction_is_enforced_on_the_next_request(self):
        """No token revocation needed: request.user is loaded from the DB per request."""
        self.authenticate(self.manager)
        self.assertEqual(self.client.get(reverse('invoice-list')).status_code, 200)

        owner_client = APIClient()
        token = LoginSerializer.get_token(self.owner)
        owner_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        owner_client.put(url(self.manager), {'role': 'manager', 'levels': levels_for(Role.MANAGER, finance=OFF)}, format='json')

        self.assertEqual(self.client.get(reverse('invoice-list')).status_code, 403)


class ModuleAccessLockTests(TransactionTestCase):
    """The shared row lock: a writer holding `locked_staff` blocks the module-access
    PUT and a role PATCH until it commits (needs real commits, so no TestCase wrap)."""

    def _fixture_teardown(self):
        pass  # see residents/tests/test_lock_ordering.py: the default flush wipes seeded tables

    def setUp(self):
        self.tenant = AuthAPITestCase.create_tenant('Lock Tenant')
        self.owner = AuthAPITestCase.create_owner(self.tenant, email='lock@module-access.example.com')
        self.staff = AuthAPITestCase.create_user(
            self.tenant, Role.MANAGER, 'staff@module-access.example.com', phone='9811100011'
        )
        token = LoginSerializer.get_token(self.owner)
        self.auth = f'Bearer {token.access_token}'

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        User.objects.filter(tenant=self.tenant).delete()
        self.tenant.delete()

    def _blocked_until_released(self, call):
        holding, release, done = threading.Event(), threading.Event(), threading.Event()
        result = {}

        def hold_lock():
            try:
                with locked_staff(self.staff.pk, self.tenant):
                    holding.set()
                    release.wait(timeout=10)
            finally:
                connection.close()

        def writer():
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=self.auth)
                result['status'] = call(client).status_code
            finally:
                done.set()
                connection.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(holding.wait(timeout=10))
        thread = threading.Thread(target=writer)
        thread.start()
        time.sleep(0.6)
        blocked = not done.is_set()  # the writer is waiting on the row lock
        release.set()
        holder.join(timeout=10)
        thread.join(timeout=10)
        return blocked, result.get('status')

    def test_module_access_put_waits_for_the_row_lock(self):
        levels = levels_for(Role.MANAGER, finance=VIEW)
        blocked, status = self._blocked_until_released(
            lambda c: c.put(url(self.staff), {'role': 'manager', 'levels': levels}, format='json')
        )
        self.assertTrue(blocked)
        self.assertEqual(status, 200)

    def test_role_patch_waits_for_the_same_row_lock(self):
        blocked, status = self._blocked_until_released(
            lambda c: c.patch(reverse('staff-detail', args=[self.staff.id]), {'first_name': 'Locked'}, format='json')
        )
        self.assertTrue(blocked)
        self.assertEqual(status, 200)

    def test_role_patch_then_put_with_stale_role_conflicts(self):
        """The sequence the lock makes deterministic: PATCH role first, then a PUT
        carrying the role the client last saw is rejected, never applied."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(
            client.patch(reverse('staff-detail', args=[self.staff.id]), {'role': Role.RECEPTIONIST}, format='json').status_code,
            200,
        )
        response = client.put(
            url(self.staff), {'role': 'manager', 'levels': levels_for(Role.MANAGER, finance=OFF)}, format='json'
        )
        self.assertEqual(response.status_code, 409)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, Role.RECEPTIONIST)
        self.assertIsNone(self.staff.module_access)
