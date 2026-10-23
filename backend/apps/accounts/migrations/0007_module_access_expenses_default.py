"""Module 20 adds an `expenses` entry to the module-access registry. Staff
with a saved override would otherwise resolve it to `off` (fail-closed — see
apps/core/modules.py). Owner decision 2026-10-16: give them the role default
instead (Manager -> full; Receptionist's default is off, so nothing to do)."""
from django.db import migrations

ROLE_DEFAULTS = {'manager': 'full'}


def add_expenses_level(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.filter(role__in=ROLE_DEFAULTS, module_access__isnull=False):
        access = user.module_access
        if not isinstance(access, dict) or access.get('base_role') != user.role:
            continue  # all-off or voided by a role change — leave as is
        levels = access.get('levels')
        if not isinstance(levels, dict) or 'expenses' in levels:
            continue
        levels['expenses'] = ROLE_DEFAULTS[user.role]
        user.save(update_fields=['module_access'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_tenant_fiscal_year_start_month'),
    ]

    operations = [
        migrations.RunPython(add_expenses_level, migrations.RunPython.noop),
    ]
