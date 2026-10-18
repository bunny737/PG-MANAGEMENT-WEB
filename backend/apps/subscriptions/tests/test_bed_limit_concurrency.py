"""Bed-cap races. Both bed creation and plan selection take the tenant's
Subscription row lock, so they serialize. Needs real commits on separate
connections, so this can't be a transaction-wrapped TestCase."""
import threading
import time
from unittest import mock

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.serializers import LoginSerializer
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Property
from apps.subscriptions.models import BedLedgerEntry, Plan, Subscription
from apps.subscriptions.tests.base import SubscriptionAPITestCase

ROUNDS = 6


def run_race(test, calls):
    """Fire `(name, auth_header, fn)` calls together; return {name: status}."""
    barrier = threading.Barrier(len(calls))
    results, errors = {}, []

    def run(name, auth, fn):
        try:
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=auth)
            barrier.wait(timeout=10)
            results[name] = fn(client).status_code
        except Exception as exc:  # noqa: BLE001 - surfaced through `errors`
            errors.append((name, exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=call) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    test.assertEqual(errors, [], f'a request raised instead of responding: {errors}')
    return results


class BedLimitConcurrencyTests(TransactionTestCase):
    def _fixture_teardown(self):
        # Keep migration-seeded tables (plans, platform_config, ...) intact;
        # tearDown removes exactly what this test created.
        pass

    def setUp(self):
        self.tenant = SubscriptionAPITestCase.create_tenant('Bed Race Tenant')
        self.owner = SubscriptionAPITestCase.create_owner(self.tenant, email='bed-race@concurrency.example.com')
        self.property = SubscriptionAPITestCase.create_property(self.tenant)
        self.room = SubscriptionAPITestCase.create_room(
            SubscriptionAPITestCase.create_floor(self.property), sharing_type=8,
        )
        self.capped = SubscriptionAPITestCase.create_plan(
            name='Race Capped', max_properties=None, max_residents_per_property=None, max_beds=3,
        )
        self.open = SubscriptionAPITestCase.create_plan(
            name='Race Open', max_properties=None, max_residents_per_property=None,
        )
        self.subscription = SubscriptionAPITestCase.create_subscription(self.tenant, plan=self.open)
        token = LoginSerializer.get_token(self.owner)
        self.auth = f'Bearer {token.access_token}'

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            Property.objects.filter(pk=self.property.pk).delete()
            BedLedgerEntry.objects.filter(tenant_id=self.tenant.id).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
            Subscription.objects.filter(tenant=self.tenant).delete()
        Plan.objects.filter(pk__in=[self.capped.pk, self.open.pk]).delete()
        self.owner.delete()
        self.tenant.delete()

    def _bed_count(self):
        with tenant_context(self.tenant.id):
            return Bed.objects.count()

    def _reset_beds(self, count):
        with tenant_context(self.tenant.id):
            Bed.objects.all().delete()
        for i in range(count):
            SubscriptionAPITestCase.create_bed(self.room, bed_number=f'R-{i}')

    def _race(self, calls):
        return run_race(self, [(name, self.auth, fn) for name, fn in calls])

    def _add_bed(self, number):
        return lambda client: client.post(
            reverse('bed-list'), {'room': str(self.room.id), 'bed_number': number}, format='json',
        )

    def test_parallel_bed_creates_at_the_limit_let_exactly_one_through(self):
        Subscription.objects.filter(pk=self.subscription.pk).update(plan=self.capped)
        for round_number in range(ROUNDS):
            self._reset_beds(2)  # one slot left under the cap of 3
            results = self._race([
                ('first', self._add_bed(f'P-{round_number}-1')),
                ('second', self._add_bed(f'P-{round_number}-2')),
            ])

            self.assertEqual(sorted(results.values()), [201, 400], f'round {round_number}: {results}')
            self.assertEqual(self._bed_count(), 3, f'round {round_number}')

    def test_selecting_a_smaller_plan_racing_a_bed_create_changes_no_limits(self):
        # A flat plan is only pending until payment, so the bed create and the
        # selection can't disagree about the cap: the tenant stays on `open`.
        select = lambda client: client.post(  # noqa: E731
            reverse('subscription-select-plan', args=[self.tenant.id]),
            {'plan': str(self.capped.id)}, format='json',
        )
        for round_number in range(ROUNDS):
            self._reset_beds(2)
            Subscription.objects.filter(pk=self.subscription.pk).update(
                plan=self.open, pending_plan=None, pending_razorpay_subscription_id='',
            )

            results = self._race([('select', select), ('bed', self._add_bed(f'D-{round_number}'))])

            self.assertEqual(sorted(results.values()), [200, 201], f'round {round_number}: {results}')
            self.subscription.refresh_from_db()
            self.assertEqual(self.subscription.plan_id, self.open.id, f'round {round_number}')
            self.assertEqual(self.subscription.pending_plan_id, self.capped.id, f'round {round_number}')


class PlanRepriceRaceTests(TransactionTestCase):
    """select_plan creates the Razorpay plan from the plan's price; an admin
    repricing at the same moment must not leave the database and Razorpay
    disagreeing. Both take the Plan row lock."""

    def _fixture_teardown(self):
        pass

    def setUp(self):
        self.tenant = SubscriptionAPITestCase.create_tenant('Reprice Race Tenant')
        self.owner = SubscriptionAPITestCase.create_owner(self.tenant, email='reprice@concurrency.example.com')
        self.admin = SubscriptionAPITestCase.create_super_admin(email='reprice-admin@concurrency.example.com')
        self.plan = SubscriptionAPITestCase.create_plan(
            name='Reprice Race', max_properties=None, max_residents_per_property=None,
        )
        self.subscription = SubscriptionAPITestCase.create_subscription(self.tenant)
        self.owner_auth = f'Bearer {LoginSerializer.get_token(self.owner).access_token}'
        self.admin_auth = f'Bearer {LoginSerializer.get_token(self.admin).access_token}'

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
            Subscription.objects.filter(tenant=self.tenant).delete()
        Plan.objects.filter(pk=self.plan.pk).delete()
        self.owner.delete()
        self.admin.delete()
        self.tenant.delete()

    def test_repricing_racing_plan_selection_never_diverges_from_razorpay(self):
        priced_at = []

        def slow_create_plan(plan):
            priced_at.append(plan.price_per_month)
            time.sleep(0.3)  # hold the window open between "read price" and "commit"
            return 'plan_race'

        select = lambda client: client.post(  # noqa: E731
            reverse('subscription-select-plan', args=[self.tenant.id]),
            {'plan': str(self.plan.id)}, format='json',
        )
        reprice = lambda client: client.patch(  # noqa: E731
            reverse('plan-detail', args=[self.plan.id]), {'price_per_month': '299.00'}, format='json',
        )
        with mock.patch('apps.subscriptions.razorpay_client.create_razorpay_plan', side_effect=slow_create_plan):
            for round_number in range(ROUNDS):
                priced_at.clear()
                Plan.objects.filter(pk=self.plan.pk).update(price_per_month='199.00', razorpay_plan_id='')
                Subscription.objects.filter(pk=self.subscription.pk).update(plan=None)

                results = run_race(self, [
                    ('select', self.owner_auth, select), ('reprice', self.admin_auth, reprice),
                ])

                self.assertNotIn(500, results.values(), f'round {round_number}: {results}')
                self.plan.refresh_from_db()
                self.assertEqual(len(priced_at), 1, f'round {round_number}: {results}')
                self.assertEqual(
                    priced_at[0], self.plan.price_per_month,
                    f'round {round_number}: Razorpay plan priced at {priced_at[0]} but the database '
                    f'says {self.plan.price_per_month} ({results})',
                )


class AdminRepriceRaceTests(TransactionTestCase):
    """The Django admin edits the same Plan row select_plan prices from. Its change
    form loads, validates and saves in one request, so it must hold the Plan lock
    for all three, and must not carry the system-managed razorpay_plan_id."""

    def _fixture_teardown(self):
        pass

    def setUp(self):
        self.tenant = SubscriptionAPITestCase.create_tenant('Admin Race Tenant')
        self.owner = SubscriptionAPITestCase.create_owner(self.tenant, email='admin-race@concurrency.example.com')
        self.staff = User.objects.create_superuser('admin-race-staff@concurrency.example.com', 'Sup3r-Secret-pw')
        self.plan = SubscriptionAPITestCase.create_plan(
            name='Admin Race', max_properties=None, max_residents_per_property=None,
        )
        self.subscription = SubscriptionAPITestCase.create_subscription(self.tenant)
        self.owner_auth = f'Bearer {LoginSerializer.get_token(self.owner).access_token}'

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
            Subscription.objects.filter(tenant=self.tenant).delete()
        Plan.objects.filter(pk=self.plan.pk).delete()
        self.owner.delete()
        self.staff.delete()
        self.tenant.delete()

    def _admin_reprice(self, price):
        def post(_client):
            client = Client()
            client.force_login(self.staff)
            url = reverse('admin:subscriptions_plan_change', args=[self.plan.pk])
            return client.post(url, {
                'name': 'Admin Race', 'pricing_type': 'flat_monthly', 'price_per_month': price,
                'is_active': 'on', 'max_properties': '', 'max_residents_per_property': '', 'max_beds': '',
                'bed_tiers-TOTAL_FORMS': '0', 'bed_tiers-INITIAL_FORMS': '0',
                'bed_tiers-MIN_NUM_FORMS': '0', 'bed_tiers-MAX_NUM_FORMS': '1000',
            })
        return post

    def test_admin_repricing_racing_plan_selection_never_diverges_from_razorpay(self):
        priced_at = []

        def slow_create_plan(plan):
            priced_at.append(plan.price_per_month)
            time.sleep(0.3)
            return 'plan_admin_race'

        select = lambda client: client.post(  # noqa: E731
            reverse('subscription-select-plan', args=[self.tenant.id]),
            {'plan': str(self.plan.id)}, format='json',
        )
        with mock.patch('apps.subscriptions.razorpay_client.create_razorpay_plan', side_effect=slow_create_plan):
            for round_number in range(ROUNDS):
                priced_at.clear()
                Plan.objects.filter(pk=self.plan.pk).update(price_per_month='199.00', razorpay_plan_id='')
                Subscription.objects.filter(pk=self.subscription.pk).update(plan=None)

                results = run_race(self, [
                    ('select', self.owner_auth, select), ('admin', 'unused', self._admin_reprice('299.00')),
                ])

                self.assertNotIn(500, results.values(), f'round {round_number}: {results}')
                self.plan.refresh_from_db()
                self.assertEqual(len(priced_at), 1, f'round {round_number}: {results}')
                self.assertEqual(
                    priced_at[0], self.plan.price_per_month,
                    f'round {round_number}: Razorpay plan priced at {priced_at[0]} but the database '
                    f'says {self.plan.price_per_month} ({results})',
                )
                # Whoever lost must not have clobbered the link select_plan stored.
                self.assertEqual(self.plan.razorpay_plan_id, 'plan_admin_race', f'round {round_number}')

    def test_admin_cannot_reprice_a_plan_once_a_tenant_has_selected_it(self):
        Plan.objects.filter(pk=self.plan.pk).update(razorpay_plan_id='plan_live')
        response = self._admin_reprice('299.00')(None)

        self.assertEqual(response.status_code, 200)  # form re-rendered with the error
        self.plan.refresh_from_db()
        self.assertEqual(str(self.plan.price_per_month), '199.00')
        self.assertEqual(self.plan.razorpay_plan_id, 'plan_live')

    def test_saving_an_unrelated_admin_edit_keeps_the_razorpay_link(self):
        # A form opened before a tenant picked the plan posts no razorpay_plan_id;
        # saving it (here just renaming) must not blank the link select_plan stored.
        Plan.objects.filter(pk=self.plan.pk).update(razorpay_plan_id='plan_live')
        client = Client()
        client.force_login(self.staff)
        response = client.post(reverse('admin:subscriptions_plan_change', args=[self.plan.pk]), {
            'name': 'Admin Race Renamed', 'pricing_type': 'flat_monthly', 'price_per_month': '199.00',
            'is_active': 'on', 'max_properties': '', 'max_residents_per_property': '', 'max_beds': '',
            'bed_tiers-TOTAL_FORMS': '0', 'bed_tiers-INITIAL_FORMS': '0',
            'bed_tiers-MIN_NUM_FORMS': '0', 'bed_tiers-MAX_NUM_FORMS': '1000',
        })

        self.assertEqual(response.status_code, 302, getattr(response, 'context_data', None))
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.name, 'Admin Race Renamed')
        self.assertEqual(self.plan.razorpay_plan_id, 'plan_live')
