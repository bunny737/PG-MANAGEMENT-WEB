from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.billing.autobilling import run_auto_billing


class Command(BaseCommand):
    """Ops fallback for the daily `billing.auto_billing` beat task. `--date`
    runs the sweep as if it were that day: the same date selects what is due
    and is stamped as the issue date, so it is a real run, not a preview."""

    help = 'Issue resident invoices due today and draft the cycles starting tomorrow.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Effective date (YYYY-MM-DD); default today (IST).')

    def handle(self, *args, **options):
        on_date = None
        if options['date']:
            try:
                on_date = date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError('Use --date YYYY-MM-DD.')
        totals = run_auto_billing(on_date)
        summary = ', '.join(f'{key}={value}' for key, value in totals.items())
        style = self.style.WARNING if totals['failed'] else self.style.SUCCESS
        self.stdout.write(style(f'Auto billing: {summary}'))
