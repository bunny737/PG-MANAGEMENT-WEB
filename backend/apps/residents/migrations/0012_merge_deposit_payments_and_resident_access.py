from django.db import migrations


class Migration(migrations.Migration):
    """Merge the deposit-payments (dev) and resident-app-access (feat/resident-identity) 0010 branches."""

    dependencies = [
        ('residents', '0010_deposit_payments'),
        ('residents', '0011_seed_access_tidy_tasks'),
    ]

    operations = []
