"""Retention, reports, admin and the seed command."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.devices import reports
from apps.devices.admin import AppVersionPolicyAdmin, mask_token
from apps.devices.models import AppInstallation, AppInstallationHistory, AppVersionPolicy
from apps.devices.tasks import purge_stale_app_data

from .base import DevicesAPITestCase


def audit_entries(action):
    """Platform-level audit rows are only readable as super admin (RLS)."""
    with tenant_context(None, is_super_admin=True):
        return list(AuditLog.objects.filter(action=action).select_related('actor'))


def make_install(days_ago=0, platform='android', flavor='prod', build=12, model='SM-S918B', os_version='14', **kw):
    seen = timezone.now() - timedelta(days=days_ago)
    return AppInstallation.objects.create(
        platform=platform, flavor=flavor, build_number=build, device_model=model, os_name='Android',
        os_version=os_version, first_seen_at=seen, last_seen_at=seen, **kw,
    )


class RetentionTests(TestCase):
    def test_purges_installs_unseen_over_180_days_and_their_history(self):
        fresh = make_install(days_ago=179)
        stale = make_install(days_ago=181)
        AppInstallationHistory.objects.create(installation=stale, build_number=1)

        purge_stale_app_data()

        self.assertEqual(list(AppInstallation.objects.all()), [fresh])
        self.assertEqual(AppInstallationHistory.objects.count(), 0)

    def test_purges_history_older_than_12_months_but_keeps_the_install(self):
        install = make_install()
        old = AppInstallationHistory.objects.create(installation=install, build_number=1)
        recent = AppInstallationHistory.objects.create(installation=install, build_number=2)
        AppInstallationHistory.objects.filter(pk=old.pk).update(recorded_at=timezone.now() - timedelta(days=366))
        AppInstallationHistory.objects.filter(pk=recent.pk).update(recorded_at=timezone.now() - timedelta(days=364))

        purge_stale_app_data()

        self.assertEqual(list(AppInstallationHistory.objects.all()), [recent])
        self.assertEqual(AppInstallation.objects.count(), 1)

    @override_settings(APP_INSTALLATION_RETENTION_DAYS=10)
    def test_retention_window_is_configurable(self):
        make_install(days_ago=11)
        purge_stale_app_data()
        self.assertEqual(AppInstallation.objects.count(), 0)

    def test_daily_periodic_task_is_seeded(self):
        from django_celery_beat.models import PeriodicTask

        task = PeriodicTask.objects.get(name='devices.purge_stale_app_data')
        self.assertEqual(task.task, 'apps.devices.tasks.purge_stale_app_data')
        self.assertTrue(task.enabled)


class ReportTests(TestCase):
    def setUp(self):
        AppVersionPolicy.objects.create(platform='android', flavor='prod', min_build=10, latest_build=14)
        for build in (9, 12, 12, 14):
            make_install(build=build)
        make_install(build=9, days_ago=30)  # inactive: excluded everywhere
        make_install(build=14, platform='ios', model='iPhone15,2', os_version='17')

    def test_active_installs_by_build(self):
        rows = reports.active_installs_by_build()
        android = {r['build_number']: r['count'] for r in rows if r['platform'] == 'android'}
        self.assertEqual(android, {9: 1, 12: 2, 14: 1})

    def test_adoption_summary_counts_below_latest_and_min(self):
        row = reports.adoption_summary()[0]
        self.assertEqual((row['active'], row['below_latest'], row['below_min']), (4, 3, 1))

    def test_installs_below_build(self):
        self.assertEqual(reports.installs_below_build('android', 'prod', 10).count(), 1)

    def test_lookup_by_user_and_installation(self):
        user = User.objects.create_user(email='u@example.com', password='x', role=Role.SUPER_ADMIN, first_name='U')
        mine = make_install(user=user)
        self.assertEqual(list(reports.lookup_installations(user=user)), [mine])
        self.assertEqual(list(reports.lookup_installations(installation_id=mine.installation_id)), [mine])

    def test_top_models_and_os_versions(self):
        self.assertEqual(reports.top_device_models()[0]['device_model'], 'SM-S918B')
        self.assertEqual(reports.top_device_models()[0]['count'], 4)
        self.assertEqual(reports.top_os_versions()[0]['os_version'], '14')


class AdminTests(DevicesAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(email='root@example.com', password='x', first_name='Root')
        self.client.force_login(self.admin_user)  # Django admin uses session auth

    def test_mask_token(self):
        self.assertEqual(mask_token(None), '—')
        self.assertEqual(mask_token('short'), '•••••')
        masked = mask_token('abcdefghijklmnopqrstuvwxyz')
        self.assertEqual(masked, 'abcd…wxyz')

    def test_installation_pages_never_show_the_raw_fcm_token(self):
        install = make_install(fcm_token='RAW-SECRET-TOKEN-1234567890')
        for url in (
            reverse('admin:devices_appinstallation_changelist'),
            reverse('admin:devices_appinstallation_change', args=[install.pk]),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertNotContains(response, 'RAW-SECRET-TOKEN-1234567890')
        self.assertContains(self.client.get(reverse('admin:devices_appinstallation_changelist')), 'RAW-…7890')

    def test_installations_are_read_only(self):
        self.assertEqual(self.client.get(reverse('admin:devices_appinstallation_add')).status_code, 403)

    def test_adoption_report_renders(self):
        make_install()
        AppVersionPolicy.objects.create(platform='android', flavor='prod')
        response = self.client.get(reverse('admin:devices_appinstallation_report'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SM-S918B')

    def policy_form_data(self, **overrides):
        data = {
            'platform': 'android', 'flavor': 'prod', 'min_build': 1, 'latest_build': 14, 'latest_version': '1.3.0',
            'store_url': '', 'release_notes': '{}', 'soft_update_enabled': 'on', 'maintenance_message': '',
            'check_interval_seconds': 21600,
        }
        data.update(overrides)
        return data

    def test_creating_and_editing_a_policy_is_audited_and_stamps_updated_by(self):
        self.client.post(reverse('admin:devices_appversionpolicy_add'), self.policy_form_data())
        policy = AppVersionPolicy.objects.get()
        self.assertEqual(policy.updated_by, self.admin_user)
        self.assertEqual(len(audit_entries('app_version_policy.created')), 1)

        self.client.post(
            reverse('admin:devices_appversionpolicy_change', args=[policy.pk]),
            self.policy_form_data(latest_build=20),
        )
        entry = audit_entries('app_version_policy.updated')[0]
        self.assertEqual(entry.before['latest_build'], 14)
        self.assertEqual(entry.after['latest_build'], 20)
        self.assertEqual(entry.actor, self.admin_user)
        self.assertEqual(entry.object_id, str(policy.pk))

    def test_raising_min_build_requires_confirmation(self):
        policy = AppVersionPolicy.objects.create(platform='android', flavor='prod', min_build=1, latest_build=14)
        url = reverse('admin:devices_appversionpolicy_change', args=[policy.pk])

        response = self.client.post(url, self.policy_form_data(min_build=10))
        self.assertEqual(response.status_code, 200)  # form re-rendered with the error
        self.assertContains(response, 'raising min_build from 1 to 10')
        policy.refresh_from_db()
        self.assertEqual(policy.min_build, 1)

        self.client.post(url, self.policy_form_data(min_build=10, confirm_min_build_raise='on'))
        policy.refresh_from_db()
        self.assertEqual(policy.min_build, 10)

    def test_lowering_min_build_needs_no_confirmation(self):
        policy = AppVersionPolicy.objects.create(platform='android', flavor='prod', min_build=10, latest_build=14)
        self.client.post(
            reverse('admin:devices_appversionpolicy_change', args=[policy.pk]), self.policy_form_data(min_build=5),
        )
        policy.refresh_from_db()
        self.assertEqual(policy.min_build, 5)

    def test_latest_build_below_min_build_is_rejected(self):
        response = self.client.post(
            reverse('admin:devices_appversionpolicy_add'), self.policy_form_data(min_build=10, latest_build=5),
        )
        self.assertContains(response, 'greater than or equal to min_build')
        self.assertEqual(AppVersionPolicy.objects.count(), 0)

    def test_deleting_a_policy_is_audited(self):
        policy = AppVersionPolicy.objects.create(platform='android', flavor='prod')
        pk = policy.pk
        self.client.post(reverse('admin:devices_appversionpolicy_delete', args=[pk]), {'post': 'yes'})
        entry = audit_entries('app_version_policy.deleted')[0]
        self.assertEqual(entry.object_id, str(pk))
        self.assertEqual(entry.before['platform'], 'android')


class SeedCommandTests(TestCase):
    def test_creates_one_row_per_platform_and_flavor_without_overwriting(self):
        AppVersionPolicy.objects.create(platform='ios', flavor='prod', min_build=7, latest_build=9)

        call_command('seed_app_version_policies', '--latest-build', '14', stdout=StringIO())

        self.assertEqual(AppVersionPolicy.objects.count(), 4)
        android = AppVersionPolicy.objects.get(platform='android', flavor='prod')
        self.assertEqual((android.min_build, android.latest_build), (1, 14))
        self.assertIn('play.google.com', android.store_url)
        self.assertEqual(AppVersionPolicy.objects.get(platform='ios', flavor='prod').min_build, 7)
