from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.notices.sweep import allocate_food_holiday_credits


class Command(BaseCommand):
    """Ops fallback for the daily `notices.allocate_food_holiday_credits` beat
    task. `--date` runs it as if it were that day (a real run, not a preview):
    holidays that ended before that date get their credits."""

    help = 'Create food-holiday credits for holidays that ended and put pending credits on draft invoices.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Effective date (YYYY-MM-DD); default today (IST).')

    def handle(self, *args, **options):
        on_date = None
        if options['date']:
            try:
                on_date = date.fromisoformat(options['date'])
            except ValueError:
                raise CommandError('Use --date YYYY-MM-DD.')
        totals = allocate_food_holiday_credits(on_date)
        summary = ', '.join(f'{key}={value}' for key, value in totals.items())
        style = self.style.WARNING if totals['failed'] else self.style.SUCCESS
        self.stdout.write(style(f'Food-holiday credits: {summary}'))
