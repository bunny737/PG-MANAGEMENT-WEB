"""Module 23: the Getting started checklist — step predicates, prerequisites,
the counted set, status precedence, target-property choice, dismissal and
tenant isolation."""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.properties.models import Building
from apps.residents.models import Resident

from .base import OnboardingAPITestCase

REQUIRED = ['add_property', 'add_building', 'add_floor', 'add_room', 'admit_resident']


class FreshOwnerTests(OnboardingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def test_no_property_only_add_property_is_open(self):
        data = self.checklist()
        self.assertEqual(data['status'], 'in_progress')
        self.assertIsNone(data['target_property'])
        self.assertEqual(data['next_step'], 'add_property')
        self.assertEqual(data['progress'], {'done': 0, 'total': 5})
        self.assertEqual([s['key'] for s in data['steps']], REQUIRED + ['record_expense'])
        self.assertIsNone(self.step(data, 'add_property')['blocked_by'])
        for key in REQUIRED[1:] + ['record_expense']:
            self.assertEqual(self.step(data, key)['blocked_by'], 'add_property', key)
            self.assertFalse(self.step(data, key)['done'])

    def test_each_step_ticks_and_unblocks_the_next(self):
        prop = self.bare_property(self.tenant)
        data = self.checklist()
        self.assertEqual(data['target_property'], {'id': str(prop.id), 'name': prop.name})
        self.assertEqual(data['next_step'], 'add_building')
        self.assertEqual(self.step(data, 'add_floor')['blocked_by'], 'add_building')
        self.assertEqual(self.step(data, 'add_building')['params'], {'property_id': str(prop.id)})

        building = self.create_building(prop, name='Main Building')
        data = self.checklist()
        self.assertEqual(data['next_step'], 'add_floor')
        self.assertEqual(self.step(data, 'add_floor')['params'],
                         {'property_id': str(prop.id), 'building_id': str(building.id)})
        self.assertEqual(self.step(data, 'add_room')['blocked_by'], 'add_floor')

        floor = self.create_floor(prop)
        data = self.checklist()
        self.assertEqual(data['next_step'], 'add_room')
        self.assertEqual(self.step(data, 'add_room')['params'],
                         {'property_id': str(prop.id), 'floor_id': str(floor.id)})

        room = self.create_room(floor)
        self.assertEqual(self.checklist()['next_step'], 'add_room', 'a room without beds is not done')

        bed = self.create_bed(room)
        data = self.checklist()
        self.assertEqual(data['next_step'], 'admit_resident')
        self.assertEqual(data['progress'], {'done': 4, 'total': 5})

        resident = self.create_resident(prop, status=Resident.Status.RESERVED)
        self.assertEqual(self.checklist()['next_step'], 'admit_resident', 'a reservation is not an admission')

        self.check_in(resident, bed)
        data = self.checklist()
        self.assertEqual(data['status'], 'completed')
        self.assertIsNone(data['next_step'])
        self.assertEqual(data['progress'], {'done': 5, 'total': 5})
        self.assertFalse(data['dismissed'], 'completing never dismisses')

    def test_admission_stays_done_after_vacating(self):
        prop = self.create_property(self.tenant)
        resident = self.admit(prop)
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=resident.pk).update(status=Resident.Status.VACATED)
        self.assertTrue(self.step(self.checklist(), 'admit_resident')['done'])

    def test_deleting_the_last_building_unticks_it(self):
        prop = self.create_property(self.tenant)  # auto-provisions the Main Building
        self.assertTrue(self.step(self.checklist(), 'add_building')['done'])
        with tenant_context(self.tenant.id):
            Building.objects.filter(property=prop).delete()
        data = self.checklist()
        self.assertFalse(self.step(data, 'add_building')['done'])
        self.assertEqual(data['next_step'], 'add_building')

    def test_expense_is_optional_and_needs_only_a_property(self):
        prop = self.bare_property(self.tenant)
        data = self.checklist()
        expense = self.step(data, 'record_expense')
        self.assertFalse(expense['required'])
        self.assertTrue(expense['permitted'])
        self.assertIsNone(expense['blocked_by'], 'open before any building or admission')
        self.assertEqual(expense['params'], {'property_id': str(prop.id)})
        self.assertEqual(expense['video_topic'], 'expenses')

        self.create_expense(prop)
        after = self.checklist()
        self.assertTrue(self.step(after, 'record_expense')['done'])
        self.assertEqual(after['progress'], data['progress'])
        self.assertEqual(after['next_step'], data['next_step'])
        self.assertEqual(after['status'], data['status'])

    def test_soft_deleted_expense_does_not_count(self):
        prop = self.create_property(self.tenant)
        self.create_expense(prop, deleted_at=timezone.now())
        self.assertFalse(self.step(self.checklist(), 'record_expense')['done'])


class TargetPropertyTests(OnboardingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def test_all_properties_targets_the_incomplete_one(self):
        done = self.create_property(self.tenant, name='Done PG')
        self.admit(done)
        todo = self.create_property(self.tenant, name='New PG')
        data = self.checklist()
        self.assertEqual(data['target_property']['id'], str(todo.id))
        self.assertEqual(data['next_step'], 'add_floor')
        with tenant_context(self.tenant.id):
            building = Building.objects.get(property=todo)
        self.assertEqual(self.step(data, 'add_floor')['params'],
                         {'property_id': str(todo.id), 'building_id': str(building.id)})

    def test_oldest_incomplete_property_wins(self):
        older = self.create_property(self.tenant, name='Older')
        self.create_property(self.tenant, name='Newer')
        self.assertEqual(self.checklist()['target_property']['id'], str(older.id))

    def test_all_complete_falls_back_to_the_oldest(self):
        older = self.create_property(self.tenant, name='Older')
        self.admit(older)
        newer = self.create_property(self.tenant, name='Newer')
        self.admit(newer, phone='9000000002', room_number='201')
        data = self.checklist()
        self.assertEqual(data['target_property']['id'], str(older.id))
        self.assertEqual(data['status'], 'completed')

    def test_explicit_property(self):
        first = self.create_property(self.tenant, name='First')
        second = self.create_property(self.tenant, name='Second')
        self.admit(second)
        data = self.checklist(property=str(second.id))
        self.assertEqual(data['target_property']['id'], str(second.id))
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(self.checklist(property=str(first.id))['status'], 'in_progress')

    def test_invisible_or_malformed_property_is_404(self):
        other = self.create_property(self.create_tenant(name='Other PG'), name='Theirs')
        self.checklist(expected_status=404, property=str(other.id))
        self.checklist(expected_status=404, property='not-a-uuid')

    def test_query_count_does_not_grow_with_properties(self):
        self.create_property(self.tenant, name='P0')
        url = reverse('onboarding-checklist')
        with CaptureQueriesContext(connection) as one:
            self.client.get(url)
        for i in range(1, 10):
            self.create_property(self.tenant, name=f'P{i}')
        with CaptureQueriesContext(connection) as ten:
            self.client.get(url)
        self.assertEqual(len(one), len(ten))


class RoleTests(OnboardingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)

    def test_receptionist_has_no_actions(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.prop)
        self.authenticate(receptionist)
        data = self.checklist()
        self.assertEqual(data['status'], 'no_actions')
        self.assertEqual(data['progress'], {'done': 0, 'total': 0})
        self.assertIsNone(data['next_step'])

    def test_unassigned_manager_has_no_actions(self):
        self.authenticate(self.create_manager(self.tenant))
        data = self.checklist()
        self.assertEqual(data['status'], 'no_actions')
        self.assertIsNone(data['target_property'])
        self.assertFalse(self.step(data, 'add_property')['permitted'])
        self.assertTrue(self.step(data, 'add_floor')['permitted'])
        self.assertEqual(self.step(data, 'add_floor')['blocked_by'], 'add_property')

    def test_assigned_manager_does_not_count_add_property(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.authenticate(manager)
        data = self.checklist()
        add_property = self.step(data, 'add_property')
        self.assertTrue(add_property['done'])
        self.assertFalse(add_property['permitted'])
        self.assertEqual(data['progress'], {'done': 1, 'total': 4})  # the auto-created building
        self.assertEqual(data['next_step'], 'add_floor')
        self.assertEqual(data['status'], 'in_progress')

    def test_manager_with_everything_done_is_completed_not_no_actions(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.admit(self.prop)
        self.authenticate(manager)
        data = self.checklist()
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['progress'], {'done': 4, 'total': 4})

    def test_restricted_manager_is_sent_where_they_can_act(self):
        # Admissions but not rooms: the older property needs a floor (not theirs to add),
        # the newer one has a bed and needs an admission (theirs).
        manager = self.create_manager(self.tenant, module_access={
            'base_role': Role.MANAGER, 'levels': {'properties': 'view', 'tenants': 'full'},
        })
        self.assign_staff(manager, self.prop)
        self.authenticate(manager)
        self.assertEqual(self.checklist()['status'], 'no_actions')

        newer = self.create_property(self.tenant, name='Newer')
        self.bed_in(newer)
        self.assign_staff(manager, newer)
        data = self.checklist()
        self.assertEqual(data['target_property']['id'], str(newer.id))
        self.assertEqual(data['next_step'], 'admit_resident')
        self.assertEqual(data['status'], 'in_progress')
        self.assertEqual(data['progress'], {'done': 0, 'total': 1})

    def test_resident_and_super_admin_are_refused(self):
        resident_user = self.create_user(self.tenant, Role.RESIDENT, 'resident@example.com')
        for user in (resident_user, self.create_super_admin()):
            self.authenticate(user)
            self.checklist(expected_status=403)
            self.assertEqual(self.client.post(reverse('onboarding-checklist-dismiss')).status_code, 403)
            self.assertEqual(self.client.delete(reverse('onboarding-checklist-dismiss')).status_code, 403)
            self.assertEqual(self.client.get(reverse('help-videos')).status_code, 403)


class DismissTests(OnboardingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)
        self.url = reverse('onboarding-checklist-dismiss')

    def audit_actions(self):
        with tenant_context(self.tenant.id):
            return list(AuditLog.objects.filter(action__startswith='onboarding.').values_list('action', flat=True))

    def test_dismiss_is_idempotent_and_audited_once(self):
        self.assertEqual(self.client.post(self.url).status_code, 204)
        first = User.objects.get(pk=self.owner.pk).onboarding_dismissed_at
        self.assertIsNotNone(first)
        self.assertEqual(self.client.post(self.url).status_code, 204)
        self.assertEqual(User.objects.get(pk=self.owner.pk).onboarding_dismissed_at, first)
        self.assertEqual(self.audit_actions(), ['onboarding.dismissed'])
        self.assertTrue(self.checklist()['dismissed'])
        self.assertTrue(self.client.get(reverse('auth-me')).data['onboarding_dismissed'])

    def test_restore_without_dismiss_does_nothing(self):
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(self.audit_actions(), [])

    def test_restoring_a_completed_checklist_shows_it_completed(self):
        self.admit(self.create_property(self.tenant))
        self.client.post(self.url)
        self.client.delete(self.url)
        data = self.checklist()
        self.assertFalse(data['dismissed'])
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(sorted(self.audit_actions()), ['onboarding.dismissed', 'onboarding.restored'])

    def test_dismissal_is_per_user(self):
        self.client.post(self.url)
        manager = self.create_manager(self.tenant)
        self.authenticate(manager)
        self.assertFalse(self.checklist()['dismissed'])


class TenantIsolationTests(OnboardingAPITestCase):
    def test_another_tenants_data_never_ticks_steps(self):
        theirs = self.create_tenant(name='Theirs')
        their_prop = self.create_property(theirs, name='Their PG')
        self.admit(their_prop)
        self.create_expense(their_prop)

        mine = self.create_tenant(name='Mine')
        self.authenticate(self.create_owner(mine, email='mine@example.com'))
        data = self.checklist()
        self.assertIsNone(data['target_property'])
        self.assertEqual(data['progress'], {'done': 0, 'total': 5})
        self.assertFalse(any(step['done'] for step in data['steps']))
        self.checklist(expected_status=404, property=str(their_prop.id))
