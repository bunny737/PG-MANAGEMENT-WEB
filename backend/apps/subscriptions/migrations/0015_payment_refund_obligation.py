# Module 22: the refund obligation becomes structured fields on the retained
# SubscriptionPayment row (the tenant purge deletes the audit rows that used to be the only
# record). Order matters: add the fields, back-fill from the legacy audit flags, and only
# then add the combination constraint, so it is created against data that already satisfies it.
import django.core.validators
from django.db import migrations, models

from apps.core.tenancy import tenant_context

LEGACY_ACTION = 'subscription.payment_needs_refund'


def backfill_pending_refunds(apps, schema_editor):
    AuditLog = apps.get_model('audit', 'AuditLog')
    SubscriptionPayment = apps.get_model('subscriptions', 'SubscriptionPayment')
    # audit_logs and subscription_payments are both under FORCE'd RLS and a migration has no
    # request context: without the super-admin GUCs these queries would silently see no rows.
    with tenant_context(is_super_admin=True):
        flags = AuditLog.objects.filter(action=LEGACY_ACTION).order_by('created_at')
        for entry in flags.iterator():
            payment_id = (entry.after or {}).get('razorpay_payment_id') or ''
            if not payment_id:
                continue
            SubscriptionPayment.objects.filter(
                razorpay_payment_id=payment_id, refund_status='none',
            ).update(refund_status='pending', refund_flagged_at=entry.created_at)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0014_webhook_event_ordering'),
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionpayment',
            name='refund_status',
            field=models.CharField(
                choices=[('none', 'No refund needed'), ('pending', 'Refund pending'),
                         ('refunded', 'Refunded'), ('waived', 'Waived')],
                db_index=True, default='none', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='refund_flagged_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='refund_resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='refund_reference',
            field=models.CharField(
                blank=True, default='', max_length=64,
                validators=[django.core.validators.RegexValidator(
                    '^rfnd_[A-Za-z0-9]+$', 'Enter a Razorpay refund id (rfnd_...).')],
            ),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='refund_resolution',
            field=models.CharField(
                blank=True,
                choices=[('refunded_via_razorpay', 'Refunded via Razorpay'),
                         ('waived_duplicate', 'Waived: duplicate'),
                         ('waived_credit_applied', 'Waived: credit applied'),
                         ('waived_below_threshold', 'Waived: below threshold'),
                         ('waived_other', 'Waived: other')],
                default='', max_length=30,
            ),
        ),
        migrations.RunPython(backfill_pending_refunds, noop_reverse),
        migrations.AddConstraint(
            model_name='subscriptionpayment',
            constraint=models.CheckConstraint(
                name='payment_refund_state_valid',
                condition=models.Q(models.Q(('refund_flagged_at__isnull', True), ('refund_reference', ''), ('refund_resolution', ''), ('refund_resolved_at__isnull', True), ('refund_status', 'none')), models.Q(('refund_flagged_at__isnull', False), ('refund_reference', ''), ('refund_resolution', ''), ('refund_resolved_at__isnull', True), ('refund_status', 'pending')), models.Q(('refund_flagged_at__isnull', False), ('refund_resolution', 'refunded_via_razorpay'), ('refund_resolved_at__isnull', False), ('refund_status', 'refunded'), models.Q(('refund_reference', ''), _negated=True)), models.Q(('refund_flagged_at__isnull', False), ('refund_reference', ''), ('refund_resolution__startswith', 'waived_'), ('refund_resolved_at__isnull', False), ('refund_status', 'waived')), _connector='OR'),
            ),
        ),
    ]
