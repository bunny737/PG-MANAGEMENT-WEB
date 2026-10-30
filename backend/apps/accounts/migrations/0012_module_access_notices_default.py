"""Module 24 adds a `notices` entry to the module-access registry. Staff with a
saved override would otherwise resolve it to `off` (fail-closed — see
apps/core/modules.py). As with expenses (0007), give them the role default
instead: Manager -> full, Receptionist -> view."""
from django.db import migrations

ROLE_DEFAULTS = {'manager': 'full', 'receptionist': 'view'}


def add_notices_level(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.filter(role__in=ROLE_DEFAULTS, module_access__isnull=False):
        access = user.module_access
        if not isinstance(access, dict) or access.get('base_role') != user.role:
            continue  # all-off or voided by a role change — leave as is
        levels = access.get('levels')
        if not isinstance(levels, dict) or 'notices' in levels:
            continue
        levels['notices'] = ROLE_DEFAULTS[user.role]
        user.save(update_fields=['module_access'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_user_onboarding_dismissed_at'),
    ]

    operations = [
        migrations.RunPython(add_notices_level, migrations.RunPython.noop),
    ]
