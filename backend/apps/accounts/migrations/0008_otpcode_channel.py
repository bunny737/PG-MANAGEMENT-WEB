"""Email OTP login: codes carry the channel they were issued for. Every code
issued before this migration was a phone code, so existing rows backfill as
'phone'; the default is not kept, so new code must name the channel."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_module_access_expenses_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='otpcode',
            name='channel',
            field=models.CharField(choices=[('phone', 'Phone'), ('email', 'Email')], default='phone', max_length=10),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name='otpcode',
            index=models.Index(fields=['user', 'channel', 'used', '-created_at'], name='otp_user_chan_used_idx'),
        ),
    ]
