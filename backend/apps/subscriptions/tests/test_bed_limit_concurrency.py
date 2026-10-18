"""Bed-cap races. Both bed creation and plan selection take the tenant's
Subscription row lock, so they serialize. Needs real commits on separate
connections, so this can't be a transaction-wrapped TestCase."""
import threading

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.serializers import LoginSerializer
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Property
from apps.subscriptions.models import BedLedgerEntry, Plan, Subscription
from apps.subscriptions.tests.base import SubscriptionAPITestCase

ROUNDS = 6


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
        barrier = threading.Barrier(len(calls))
        results, errors = {}, []

        def run(name, fn):
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=self.auth)
                barrier.wait(timeout=10)
                results[name] = fn(client).status_code
            except Exception as exc:  # noqa: BLE001 - surfaced through `errors`
                errors.append((name, exc))
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(name, fn)) for name, fn in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [], f'a request raised instead of responding: {errors}')
        return results

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

    def test_downgrade_racing_a_bed_create_never_leaves_the_tenant_over_the_cap(self):
        select = lambda client: client.post(  # noqa: E731
            reverse('subscription-select-plan', args=[self.tenant.id]),
            {'plan': str(self.capped.id)}, format='json',
        )
        for round_number in range(ROUNDS):
            self._reset_beds(3)
            Subscription.objects.filter(pk=self.subscription.pk).update(plan=self.open)

            results = self._race([('select', select), ('bed', self._add_bed(f'D-{round_number}'))])

            self.assertNotIn(500, results.values(), f'round {round_number}: {results}')
            self.subscription.refresh_from_db()
            if self.subscription.plan_id == self.capped.id:
                self.assertLessEqual(
                    self._bed_count(), 3, f'round {round_number}: over the cap on the smaller plan ({results})',
                )
            # Exactly one of the two requests loses: either the downgrade is
            # refused (a 4th bed exists) or the bed is refused (cap now applies).
            self.assertEqual(sorted(results.values()), [200, 400] if 201 not in results.values() else [201, 400],
                             f'round {round_number}: {results}')
