"""Registry + resolver tests for per-staff module access (apps/core/modules.py).

Users here are unsaved `User` instances: resolution is pure and in-memory.
"""
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase

from apps.accounts.models import User
from apps.core.modules import (
    FULL,
    GRANTABLE_CODES,
    MODULE_KEYS,
    MODULES,
    OFF,
    ROLE_DEFAULT_LEVELS,
    VIEW,
    codes_for_level,
    describe_access,
    effective_levels,
    module_levels,
    role_default_levels,
    storage_value,
    validate_levels_payload,
)
from apps.core.roles import STAFF_ROLES, Role, permissions_for, permissions_for_user

NON_GRANTABLE = {
    'manage_properties', 'manage_staff_accounts', 'assign_staff_to_properties',
    'manage_tenant_settings', 'manage_subscription', 'view_audit_logs', 'manage_tenants',
    'view_own_notifications', 'manage_notification_preferences',
}


def staff(role=Role.MANAGER, module_access=None):
    return User(role=role, module_access=module_access)


def all_off():
    return {m: OFF for m in MODULE_KEYS}


class RegistryTests(SimpleTestCase):
    def test_role_defaults_reproduce_the_permission_matrix_exactly(self):
        """The hand-written defaults and PERMISSION_MATRIX must not drift apart."""
        for role in STAFF_ROLES:
            defaults = ROLE_DEFAULT_LEVELS[role]
            default_codes = set()
            for module, level in defaults.items():
                default_codes |= codes_for_level(module, level)
            self.assertEqual(
                default_codes, set(permissions_for(role)) & GRANTABLE_CODES, role,
            )

    def test_defaults_cover_every_module_with_a_supported_level(self):
        for role in STAFF_ROLES:
            self.assertEqual(set(ROLE_DEFAULT_LEVELS[role]), set(MODULE_KEYS))
            for module, level in ROLE_DEFAULT_LEVELS[role].items():
                self.assertIn(level, module_levels(module))

    def test_full_includes_every_view_code(self):
        for module in MODULE_KEYS:
            levels = module_levels(module)
            for lower, higher in zip(levels, levels[1:]):
                self.assertTrue(codes_for_level(module, lower) <= codes_for_level(module, higher))

    def test_off_grants_nothing(self):
        for module in MODULE_KEYS:
            self.assertEqual(codes_for_level(module, OFF), frozenset())

    def test_unsupported_level_raises(self):
        with self.assertRaises(ValueError):
            codes_for_level('complaints', VIEW)  # complaints supports only off/full

    def test_non_grantable_codes_are_never_in_the_registry(self):
        self.assertFalse(GRANTABLE_CODES & NON_GRANTABLE)

    def test_manage_property_settings_is_grantable_under_properties(self):
        self.assertIn('manage_property_settings', codes_for_level('properties', FULL))
        self.assertNotIn('manage_property_settings', codes_for_level('properties', VIEW))

    def test_single_level_modules(self):
        for module in ('dashboard', 'reports', 'complaints', 'visitors'):
            self.assertEqual(module_levels(module), [OFF, FULL])
        for module in ('properties', 'tenants', 'finance', 'expenses'):
            self.assertEqual(module_levels(module), [OFF, VIEW, FULL])

    def test_expenses_view_and_manage_split(self):
        self.assertEqual(codes_for_level('expenses', VIEW), {'view_expenses'})
        self.assertEqual(codes_for_level('expenses', FULL), {'view_expenses', 'manage_expenses'})
        self.assertEqual(ROLE_DEFAULT_LEVELS[Role.MANAGER]['expenses'], FULL)
        self.assertEqual(ROLE_DEFAULT_LEVELS[Role.RECEPTIONIST]['expenses'], OFF)


class ResolverTests(SimpleTestCase):
    def test_non_staff_roles_ignore_any_override(self):
        override = {'base_role': 'owner', 'levels': all_off()}
        for role in (Role.OWNER, Role.SUPER_ADMIN, Role.RESIDENT):
            user = User(role=role, module_access=override)
            self.assertEqual(permissions_for_user(user), permissions_for(role))
            self.assertIsNone(effective_levels(user))

    def test_unsaved_and_anonymous_users(self):
        self.assertEqual(permissions_for_user(User()), permissions_for(''))
        self.assertEqual(permissions_for_user(AnonymousUser()), [])
        self.assertEqual(permissions_for_user(None), [])

    def test_null_means_role_defaults(self):
        for role in STAFF_ROLES:
            self.assertEqual(permissions_for_user(staff(role)), permissions_for(role))
            self.assertEqual(effective_levels(staff(role)), role_default_levels(role))

    def test_non_dict_json_is_all_off(self):
        for raw in ([], ['finance'], 'full', 7, True, 0):
            self.assertEqual(effective_levels(staff(module_access=raw)), all_off(), raw)

    def test_raw_empty_dict_is_all_off_never_defaults(self):
        user = staff(module_access={})
        self.assertEqual(effective_levels(user), all_off())
        perms = set(permissions_for_user(user))
        self.assertFalse(perms & GRANTABLE_CODES)
        self.assertNotEqual(perms, set(permissions_for(Role.MANAGER)))

    def test_dict_without_base_role_is_all_off(self):
        user = staff(module_access={'levels': {m: FULL for m in MODULE_KEYS}})
        self.assertEqual(effective_levels(user), all_off())

    def test_wrong_base_role_falls_back_to_role_defaults(self):
        user = staff(Role.RECEPTIONIST, {'base_role': 'manager', 'levels': {m: FULL for m in MODULE_KEYS}})
        self.assertEqual(effective_levels(user), role_default_levels(Role.RECEPTIONIST))
        self.assertEqual(permissions_for_user(user), permissions_for(Role.RECEPTIONIST))

    def test_missing_or_malformed_levels_is_all_off(self):
        for raw in (
            {'base_role': 'manager'},
            {'base_role': 'manager', 'levels': None},
            {'base_role': 'manager', 'levels': 'full'},
            {'base_role': 'manager', 'levels': ['finance']},
        ):
            self.assertEqual(effective_levels(staff(module_access=raw)), all_off(), raw)

    def test_known_module_missing_from_levels_is_off_others_unaffected(self):
        levels = {m: FULL for m in MODULE_KEYS}
        del levels['finance']
        resolved = effective_levels(staff(module_access={'base_role': 'manager', 'levels': levels}))
        self.assertEqual(resolved['finance'], OFF)
        self.assertEqual(resolved['tenants'], FULL)

    def test_unknown_module_key_is_ignored(self):
        levels = {m: FULL for m in MODULE_KEYS}
        levels['retired_module'] = FULL
        resolved = effective_levels(staff(module_access={'base_role': 'manager', 'levels': levels}))
        self.assertNotIn('retired_module', resolved)
        self.assertEqual(set(resolved), set(MODULE_KEYS))

    def test_invalid_or_unsupported_level_is_off(self):
        levels = {m: FULL for m in MODULE_KEYS}
        levels['complaints'] = VIEW      # not supported for complaints
        levels['finance'] = 'superuser'  # nonsense
        levels['reports'] = None         # wrong type
        levels['visitors'] = ['full']    # unhashable-ish junk
        resolved = effective_levels(staff(module_access={'base_role': 'manager', 'levels': levels}))
        self.assertEqual(resolved['complaints'], OFF)
        self.assertEqual(resolved['finance'], OFF)
        self.assertEqual(resolved['reports'], OFF)
        self.assertEqual(resolved['visitors'], OFF)
        self.assertEqual(resolved['tenants'], FULL)

    def test_override_replaces_grantable_codes_and_keeps_the_rest(self):
        levels = all_off()
        levels['finance'] = VIEW
        perms = set(permissions_for_user(
            staff(module_access={'base_role': 'manager', 'levels': levels})
        ))
        self.assertEqual(perms & GRANTABLE_CODES, set(codes_for_level('finance', VIEW)))
        # Non-grantable codes the role had are untouched.
        self.assertTrue({'view_own_notifications', 'manage_notification_preferences'} <= perms)
        self.assertFalse(perms & (NON_GRANTABLE - {'view_own_notifications', 'manage_notification_preferences'}))

    def test_properties_view_revokes_property_settings(self):
        levels = {m: FULL for m in MODULE_KEYS}
        levels['properties'] = VIEW
        perms = set(permissions_for_user(
            staff(module_access={'base_role': 'manager', 'levels': levels})
        ))
        self.assertNotIn('manage_property_settings', perms)
        self.assertIn('view_property_features', perms)

    def test_receptionist_can_be_upgraded_but_never_gains_non_grantable_codes(self):
        levels = {m: FULL for m in MODULE_KEYS}
        perms = set(permissions_for_user(
            staff(Role.RECEPTIONIST, {'base_role': 'receptionist', 'levels': levels})
        ))
        self.assertIn('manage_invoices', perms)
        self.assertFalse(perms & {
            'manage_properties', 'manage_staff_accounts', 'assign_staff_to_properties',
            'manage_tenant_settings', 'manage_subscription', 'view_audit_logs', 'manage_tenants',
        })


class WritePayloadTests(SimpleTestCase):
    def full(self):
        return {m: FULL if FULL in MODULES[m] else OFF for m in MODULE_KEYS}

    def test_valid_complete_payload(self):
        clean, errors = validate_levels_payload(self.full())
        self.assertEqual(errors, {})
        self.assertEqual(clean, self.full())

    def test_missing_unknown_and_unsupported_are_rejected(self):
        payload = self.full()
        del payload['reports']
        payload['mystery'] = FULL
        payload['complaints'] = VIEW
        payload['finance'] = 'bogus'
        clean, errors = validate_levels_payload(payload)
        self.assertIsNone(clean)
        self.assertEqual(set(errors), {'reports', 'mystery', 'complaints', 'finance'})

    def test_non_dict_is_rejected(self):
        for bad in (None, [], 'full', 3):
            clean, errors = validate_levels_payload(bad)
            self.assertIsNone(clean)
            self.assertIn('levels', errors)

    def test_storage_value_normalizes_defaults_to_null(self):
        for role in STAFF_ROLES:
            self.assertIsNone(storage_value(role, role_default_levels(role)))
        custom = role_default_levels(Role.MANAGER)
        custom['finance'] = VIEW
        self.assertEqual(
            storage_value(Role.MANAGER, custom), {'base_role': 'manager', 'levels': custom}
        )

    def test_describe_access_shape(self):
        data = describe_access(staff(Role.RECEPTIONIST))
        self.assertEqual(data['role'], 'receptionist')
        self.assertFalse(data['customized'])
        by_key = {m['key']: m for m in data['modules']}
        self.assertEqual([m['key'] for m in data['modules']], list(MODULE_KEYS))
        self.assertEqual(by_key['finance']['levels'], [OFF, VIEW, FULL])
        self.assertEqual(by_key['visitors']['levels'], [OFF, FULL])
        self.assertEqual(by_key['visitors']['level'], FULL)
        self.assertEqual(by_key['tenants']['default_level'], VIEW)
