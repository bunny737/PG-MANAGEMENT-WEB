"""Pre-release check for migration accounts.0013 (Module 26): list any user whose role is
already `resident`.

Module 26 turns `role='resident'` into a tenant-less, self-created app account. Migration 0013
refuses to run when such rows exist, because it cannot tell what they were meant to be. Run this
against the target database BEFORE the release (docs/deployment-manual.md, section 17): zero rows
means the migration will pass; any rows mean stop the release and write the reviewed change
described in the migration's docstring.

Read-only. Exit status 1 when rows exist, so a release script can gate on it.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.core.roles import Role


class Command(BaseCommand):
    help = 'List users with role=resident (blocks migration accounts.0013). Exits 1 if any exist.'

    def handle(self, *args, **options):
        rows = list(
            User.objects.filter(role=Role.RESIDENT)
            .order_by('created_at')
            .values_list('id', 'tenant_id', 'email', 'phone', 'is_active', 'created_at')
        )
        if not rows:
            self.stdout.write(self.style.SUCCESS('No role=resident users. Migration accounts.0013 can run.'))
            return
        self.stdout.write('id\ttenant_id\temail\tphone\tis_active\tcreated_at')
        for row in rows:
            self.stdout.write('\t'.join('' if value is None else str(value) for value in row))
        raise CommandError(
            f'{len(rows)} role=resident user(s) found. Stop the release: migration accounts.0013 '
            'will refuse to run until they are handled by a separately reviewed change.'
        )
