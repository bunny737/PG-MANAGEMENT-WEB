"""Per-staff module access (Owner-configurable permissions for Manager/Receptionist).

PRD §6 fixes one permission set per role. The owner asked (2026-10-12) to tune
that per staff member, so each staff user may carry a `module_access` override:

    {"base_role": "manager", "levels": {"finance": "view", "visitors": "off", ...}}

A *module* groups existing permission codes; a *level* (off < view < full) picks
how much of the module a person gets. Levels are cumulative: the codes for a
level are the union of every level up to and including it.

Only codes listed in MODULES are grantable. Everything else (manage_properties,
manage_staff_accounts, assign_staff_to_properties, manage_tenant_settings,
manage_subscription, view_audit_logs, manage_tenants, notification codes) stays
role-only, so an override can never escalate beyond what the registry allows.

Resolution is fail-closed — see `effective_levels`. WHEN YOU ADD A MODULE: staff
who already have a saved override resolve the new module to `off` (they do not
inherit the role default); only never-customized staff (NULL) pick up the new
role default. Decide whether the release also needs a data migration that sets
the new module to the role default for existing overrides.
"""
from .roles import STAFF_ROLES, Role, permissions_for

OFF = 'off'
VIEW = 'view'
FULL = 'full'
LEVEL_ORDER = (OFF, VIEW, FULL)

# module -> {level: codes ADDED at that level}. `off` is implicit (no codes).
# Dashboard/Reports/Complaints/Visitors only support off/full: their manage_*
# codes cover reads and writes today, so a genuine view-only level would need
# new view_* codes plus method-aware enforcement (out of scope).
MODULES = {
    'dashboard': {FULL: ('view_dashboard',)},
    'properties': {
        VIEW: ('view_property_features',),
        FULL: ('manage_property_features', 'manage_rooms_beds', 'manage_property_settings'),
    },
    'tenants': {
        VIEW: ('view_resident_profile',),
        FULL: ('manage_residents', 'manage_admissions', 'manage_allocations', 'manage_deposits'),
    },
    'finance': {
        VIEW: ('view_finance', 'view_activity_timeline'),
        FULL: ('manage_invoices', 'manage_payments', 'manage_discounts'),
    },
    'reports': {FULL: ('view_reports',)},
    'complaints': {FULL: ('manage_complaints',)},
    'visitors': {FULL: ('manage_visitors',)},
}
MODULE_KEYS = tuple(MODULES)


def module_levels(module):
    """Supported levels for a module, lowest first, always starting with `off`."""
    return [OFF] + [lvl for lvl in LEVEL_ORDER[1:] if lvl in MODULES[module]]


def codes_for_level(module, level):
    """Cumulative permission codes for `level` of `module` (union of all levels up to it)."""
    supported = module_levels(module)
    if level not in supported:
        raise ValueError(f'{level!r} is not a supported level for module {module!r}')
    codes = set()
    for lvl in supported[1:supported.index(level) + 1]:
        codes.update(MODULES[module][lvl])
    return frozenset(codes)


GRANTABLE_CODES = frozenset(code for levels in MODULES.values() for codes in levels.values() for code in codes)

# Hand-written on purpose (not derived from PERMISSION_MATRIX) so a drift between
# the two is caught by a test instead of silently changing someone's access.
ROLE_DEFAULT_LEVELS = {
    Role.MANAGER: {m: FULL for m in MODULE_KEYS},
    Role.RECEPTIONIST: {
        'dashboard': OFF,
        'properties': VIEW,
        'tenants': VIEW,
        'finance': OFF,
        'reports': OFF,
        'complaints': OFF,
        'visitors': FULL,
    },
}


def role_default_levels(role):
    """Default level per module for a staff role, or None for non-staff roles."""
    defaults = ROLE_DEFAULT_LEVELS.get(role)
    return dict(defaults) if defaults is not None else None


def _all_off():
    return {m: OFF for m in MODULE_KEYS}


def effective_levels(user):
    """Level per module for a staff user, or None if `user` isn't a staff role.

    Fail-closed resolution of the stored `module_access`:

    - NULL                                   -> role defaults
    - not a dict                             -> every module off
    - dict without a `base_role` key (incl. {}) -> every module off
    - `base_role` != current role            -> role defaults (a role change
                                                intentionally voids the override)
    - `levels` missing / not a dict          -> every module off
    - module missing from `levels`           -> that module off
    - unknown module key in `levels`         -> ignored
    - invalid/unsupported level for a module -> that module off
    """
    role = getattr(user, 'role', None)
    if role not in STAFF_ROLES:
        return None
    raw = getattr(user, 'module_access', None)
    if raw is None:
        return role_default_levels(role)
    if not isinstance(raw, dict) or 'base_role' not in raw:
        return _all_off()
    if raw['base_role'] != role:
        return role_default_levels(role)
    levels = raw.get('levels')
    if not isinstance(levels, dict):
        return _all_off()
    resolved = {}
    for module in MODULE_KEYS:
        level = levels.get(module, OFF)
        resolved[module] = level if isinstance(level, str) and level in module_levels(module) else OFF
    return resolved


def resolve_permissions(user):
    """Sorted permission codes for a user, honouring a staff member's override."""
    role = getattr(user, 'role', None)
    base = set(permissions_for(role))
    if getattr(user, 'module_access', None) is None:
        return sorted(base)  # NULL == role defaults (a test pins this equality)
    levels = effective_levels(user)
    if levels is None:
        return sorted(base)  # Owner / Super Admin / Resident: override ignored
    perms = base - GRANTABLE_CODES
    for module, level in levels.items():
        perms |= codes_for_level(module, level)
    return sorted(perms)


def validate_levels_payload(levels):
    """Validate API input for a complete replacement. Returns (clean, errors).

    Strict, unlike stored-data resolution: every registry module must be present,
    unknown modules and unsupported levels are rejected.
    """
    if not isinstance(levels, dict):
        return None, {'levels': ['Expected an object mapping module to level.']}
    errors = {}
    clean = {}
    for module in levels:
        if module not in MODULES:
            errors[module] = ['Unknown module.']
    for module in MODULE_KEYS:
        if module not in levels:
            errors[module] = ['This module is required.']
            continue
        level = levels[module]
        if not isinstance(level, str) or level not in module_levels(module):
            errors[module] = [f'Unsupported level. Choose one of: {", ".join(module_levels(module))}.']
            continue
        clean[module] = level
    return (clean if not errors else None), errors


def storage_value(role, levels):
    """What to persist for `levels`: NULL when they equal the role defaults."""
    if levels == role_default_levels(role):
        return None
    return {'base_role': role, 'levels': dict(levels)}


def describe_access(user):
    """Registry + this user's current levels, for the Team Management screen."""
    levels = effective_levels(user)
    defaults = role_default_levels(user.role)
    return {
        'role': user.role,
        'customized': getattr(user, 'module_access', None) is not None,
        'modules': [
            {
                'key': module,
                'levels': module_levels(module),
                'level': levels[module],
                'default_level': defaults[module],
            }
            for module in MODULE_KEYS
        ],
    }
