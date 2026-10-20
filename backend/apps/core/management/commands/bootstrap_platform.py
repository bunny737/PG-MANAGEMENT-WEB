"""First-time production setup (WP14, docs/deployment.md "Bootstrap").

Run once by the `pglive-bootstrap` Cloud Run Job after the first migration:
seeds the app-version policies and creates the initial Super Admin from
INITIAL_SUPERADMIN_EMAIL / INITIAL_SUPERADMIN_PASSWORD (a temporary secret,
destroyed afterwards). Idempotent and non-interactive: an existing Super Admin
is never touched, so a re-run cannot reset a password. Never logs the password.
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit import log as audit_log
from apps.core.roles import Role


class Command(BaseCommand):
    help = 'Seed app-version policies and create the initial Super Admin (once).'

    def handle(self, *args, **options):
        call_command('seed_app_version_policies', stdout=self.stdout)

        User = get_user_model()
        if User.objects.filter(role=Role.SUPER_ADMIN).exists():
            self.stdout.write('Super Admin already exists; nothing to create.')
            return

        email = os.environ.get('INITIAL_SUPERADMIN_EMAIL', '').strip()
        password = os.environ.get('INITIAL_SUPERADMIN_PASSWORD', '')
        name = os.environ.get('INITIAL_SUPERADMIN_NAME', '').strip() or 'Platform Admin'
        if not email or not password:
            raise CommandError('INITIAL_SUPERADMIN_EMAIL and INITIAL_SUPERADMIN_PASSWORD must be set.')
        try:
            validate_password(password, User(email=email, first_name=name))
        except ValidationError as exc:
            raise CommandError('INITIAL_SUPERADMIN_PASSWORD is too weak: ' + ' '.join(exc.messages))

        with transaction.atomic():
            user = User.objects.create_superuser(email=email, password=password, first_name=name)
            audit_log.record(action='platform.superadmin_bootstrapped', tenant_id=None, obj=user,
                             after={'role': user.role})
        self.stdout.write(self.style.SUCCESS(
            f'Created Super Admin {user.email}. Verify login and IAP admin access, then destroy the '
            'INITIAL_SUPERADMIN_PASSWORD secret and delete the bootstrap job.'))
