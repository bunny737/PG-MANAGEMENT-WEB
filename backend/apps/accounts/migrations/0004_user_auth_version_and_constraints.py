from django.db import migrations, models
import django.db.models.functions.text


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_normalize_user_identifiers'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='auth_version',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower('email'),
                condition=models.Q(('is_active', True)),
                name='unique_active_email_lower',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_active', True)),
                fields=['phone'],
                name='unique_active_phone',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(('email__isnull', True), models.Q(('email', ''), _negated=True), _connector='OR'),
                name='user_email_not_blank',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(('phone__isnull', True), models.Q(('phone', ''), _negated=True), _connector='OR'),
                name='user_phone_not_blank',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(('role__in', ['owner', 'super_admin']), _negated=True),
                    ('email__isnull', False),
                    _connector='OR',
                ),
                name='user_owner_superadmin_requires_email',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(('email__isnull', False), ('phone__isnull', False), _connector='OR'),
                name='user_requires_email_or_phone',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(('role__in', ['manager', 'receptionist']), _negated=True),
                    ('phone__isnull', False),
                    _connector='OR',
                ),
                name='user_staff_requires_phone',
            ),
        ),
    ]
