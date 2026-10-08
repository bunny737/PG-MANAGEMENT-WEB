"""Lock-order regression: admission (check-in) vs the generic status endpoint.

Both can take a Reserved resident to Active, and both take the plan-limit
Subscription lock (check_resident_limit). If they take their locks in opposite
orders they deadlock, PostgreSQL aborts one transaction, and the untranslated
database error surfaces as a 500:

    PATCH /residents/{id}/status/        POST /admissions/
    locks Resident                       locks Bed
                                         locks Subscription
    waits for Subscription      <->      waits to update Resident

The system order for resident-status workflows is Resident -> Vacate -> Bed ->
Subscription (see services.lock_resident and the Module 10 spec).

Needs real commits on separate connections, so this can't be a
transaction-wrapped TestCase.
"""
import threading
from datetime import date

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.serializers import LoginSerializer
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Property
from apps.residents.models import Admission, Allocation, Resident
from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.tests.base import SubscriptionAPITestCase

from .test_admissions import admission_payload

ROUNDS = 8


class AdmissionVsStatusLockOrderTests(TransactionTestCase):
    def _fixture_teardown(self):
        # The default flush would also wipe migration-seeded tables (plans,
        # feature_catalog, notification templates) for the rest of the run;
        # tearDown removes exactly what this test created instead.
        pass

    def setUp(self):
        self.tenant = SubscriptionAPITestCase.create_tenant('Lock Order Tenant')
        self.owner = SubscriptionAPITestCase.create_owner(
            self.tenant, email='lock-order@concurrency.example.com'
        )
        self.property = SubscriptionAPITestCase.create_property(self.tenant)
        self.room = SubscriptionAPITestCase.create_room(
            SubscriptionAPITestCase.create_floor(self.property)
        )
        # A subscription with a finite cap is what makes check_resident_limit
        # take the row lock. With no subscription row it locks nothing, and the
        # cycle this test exists to catch can't form.
        self.plan = SubscriptionAPITestCase.create_plan(
            name='Lock Order Plan', max_residents_per_property=50
        )
        SubscriptionAPITestCase.create_subscription(self.tenant, plan=self.plan)

        token = LoginSerializer.get_token(self.owner)
        self.auth = f'Bearer {token.access_token}'

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            Allocation.objects.filter(tenant_id=self.tenant.id).delete()
            Admission.objects.filter(tenant_id=self.tenant.id).delete()
            Resident.objects.filter(tenant_id=self.tenant.id).delete()
            Property.objects.filter(pk=self.property.pk).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
            Subscription.objects.filter(tenant=self.tenant).delete()
        self.plan.delete()
        self.owner.delete()
        self.tenant.delete()

    def _race(self, resident, bed):
        """POST the admission and PATCH the status for one Reserved resident,
        released together. Returns (admission_status, patch_status)."""
        barrier = threading.Barrier(2)
        results, errors = {}, []

        def call(name, fn):
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=self.auth)
                barrier.wait(timeout=10)
                results[name] = fn(client).status_code
            except Exception as exc:  # noqa: BLE001 - surfaced through `errors`
                errors.append((name, exc))
            finally:
                connection.close()

        threads = [
            threading.Thread(target=call, args=('admission', lambda c: c.post(
                reverse('admission-list'), admission_payload(resident, bed), format='json',
            ))),
            threading.Thread(target=call, args=('status', lambda c: c.patch(
                reverse('resident-status', args=[resident.id]), {'status': 'active'}, format='json',
            ))),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [], f'a request raised instead of responding: {errors}')
        return results['admission'], results['status']

    def _run_rounds(self, tag):
        """Race a fresh Reserved resident ROUNDS times; return one
        (round, admission_status, status_status, final_resident_status) per round."""
        outcomes = []
        for index in range(ROUNDS):
            resident = SubscriptionAPITestCase.create_resident(
                self.property, phone=f'9{tag}{index:08d}', status=Resident.Status.RESERVED
            )
            bed = SubscriptionAPITestCase.create_bed(self.room, bed_number=f'B-{tag}-{index}')
            admission_status, status_status = self._race(resident, bed)
            with tenant_context(self.tenant.id):
                resident.refresh_from_db()
            outcomes.append((index, admission_status, status_status, resident.status))
        return outcomes

    def test_simultaneous_checkin_and_status_activation_never_deadlock(self):
        """A deadlock aborts one side with an unhandled database error (a 500)."""
        outcomes = self._run_rounds(1)

        deadlocked = [o for o in outcomes if 500 in o[1:3]]
        self.assertEqual(
            deadlocked, [],
            f'lock-order deadlock in {len(deadlocked)}/{ROUNDS} rounds '
            f'(round, admission, status, resident): {deadlocked}',
        )

    def test_a_reserved_resident_is_activated_exactly_once(self):
        """Admission must re-check the resident under its lock. Validated only in
        the serializer (unlocked), it checks in a resident the status endpoint
        has just activated, so both requests report success."""
        outcomes = self._run_rounds(2)

        for index, admission_status, status_status, resident_status in outcomes:
            winners = [s for s in (admission_status, status_status) if s in (200, 201)]
            self.assertEqual(
                len(winners), 1,
                f'round {index}: admission={admission_status} status={status_status} '
                '- exactly one of them may activate a Reserved resident',
            )
            self.assertEqual(resident_status, Resident.Status.ACTIVE)
