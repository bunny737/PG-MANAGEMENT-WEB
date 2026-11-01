"""Concurrency proofs for resident app access (Module 26).

Every writer of the link lifecycle takes the Resident row lock first, then re-checks "no other
active link" inside it, with the partial unique index as the backstop. These tests race the real
service functions on separate connections and assert the invariant that matters: a record never
ends up with two active links, and nothing surfaces as an unhandled database error.

Needs real commits on separate connections, so it cannot be a transaction-wrapped TestCase."""
import threading

from django.core import mail
from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.notifications.models import NotificationLog
from apps.properties.models import Building, Property
from apps.residents import access
from apps.residents.models import ResidencyLinkRequest, Resident, ResidentAccess, ResidentInvite
from apps.subscriptions.tests.base import SubscriptionAPITestCase

ROUNDS = 6


class LinkRaceTests(TransactionTestCase):
    def _fixture_teardown(self):
        # The default flush would also wipe migration-seeded tables for the rest of the run;
        # tearDown removes exactly what this test created instead.
        pass

    def setUp(self):
        helpers = SubscriptionAPITestCase
        self.tenant = helpers.create_tenant('Link Race Tenant')
        self.owner = helpers.create_owner(self.tenant, email='race-owner@concurrency.example.com')
        self.prop = helpers.create_property(self.tenant)
        self.ravi = helpers.create_user(None, Role.RESIDENT, 'ravi-race@concurrency.example.com')
        self.alice = helpers.create_user(None, Role.RESIDENT, 'alice-race@concurrency.example.com')
        self.bob = helpers.create_user(None, Role.RESIDENT, 'bob-race@concurrency.example.com')
        self.counter = 0

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            NotificationLog.objects.filter(tenant_id=self.tenant.id).delete()
            ResidentAccess.objects.filter(tenant_id=self.tenant.id).delete()
            ResidencyLinkRequest.objects.filter(tenant_id=self.tenant.id).delete()
            ResidentInvite.objects.filter(tenant_id=self.tenant.id).delete()
            Resident.objects.filter(tenant_id=self.tenant.id).delete()
            Building.objects.filter(tenant_id=self.tenant.id).delete()
            Property.objects.filter(tenant_id=self.tenant.id).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        User.objects.filter(pk__in=[self.ravi.pk, self.alice.pk, self.bob.pk, self.owner.pk]).delete()
        self.tenant.delete()

    # --- fixtures ---
    def new_resident(self):
        self.counter += 1
        return SubscriptionAPITestCase.create_resident(
            self.prop, first_name=f'R{self.counter}', phone=f'9100000{self.counter:03d}',
            email='ravi-race@concurrency.example.com', status=Resident.Status.ACTIVE,
        )

    def new_request(self, user):
        with tenant_context(self.tenant.id):
            # A loser of an earlier round may still be pending; one pending per person and PG is a rule.
            ResidencyLinkRequest.objects.filter(requester=user, property=self.prop, status='pending').delete()
            return ResidencyLinkRequest.objects.create(
                tenant_id=self.tenant.id, requester=user, property=self.prop,
            )

    def active_links(self, resident):
        with tenant_context(self.tenant.id):
            return ResidentAccess.objects.filter(resident=resident, status='active').count()

    def invite_token(self, resident):
        mail.outbox.clear()
        with tenant_context(self.tenant.id):
            access.send_invite(resident_id=resident.pk, actor=self.owner)  # on_commit runs for real here
        return mail.outbox[-1].body.split('#token=')[1].split()[0]

    # --- the race harness ---
    def race(self, *calls):
        """Run each callable on its own thread/connection, released together. Returns a list of
        ('ok', value) or ('error', exception) in the order given."""
        barrier = threading.Barrier(len(calls))
        results = [None] * len(calls)

        def run(index, fn):
            try:
                barrier.wait(timeout=10)
                with tenant_context(self.tenant.id):
                    results[index] = ('ok', fn())
            except Exception as exc:  # noqa: BLE001 - classified by the test
                results[index] = ('error', exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return results

    def assert_clean(self, results):
        """A loser must lose with an API error (409/400), never with a raw database error."""
        for kind, value in results:
            if kind == 'error':
                self.assertIsInstance(
                    value, (access.LinkExists, access.LinkRequestNotPending, access.InviteInvalid),
                    f'unexpected failure: {value!r}',
                )

    # --- tests ---
    def test_accepting_an_invite_and_approving_a_request_never_make_two_links(self):
        for _round in range(ROUNDS):
            resident = self.new_resident()
            token = self.invite_token(resident)
            request = self.new_request(self.alice)
            results = self.race(
                lambda: access.accept_invite(user=self.ravi, token=token),
                lambda: access.approve_link_request(
                    link_request_id=request.pk, resident_id=resident.pk, actor=self.owner,
                ),
            )
            self.assert_clean(results)
            self.assertEqual(self.active_links(resident), 1, results)
            self.assertEqual([kind for kind, _ in results].count('ok'), 1, results)

    def test_two_requests_approved_for_the_same_record_make_one_link(self):
        for _round in range(ROUNDS):
            resident = self.new_resident()
            first, second = self.new_request(self.alice), self.new_request(self.bob)
            results = self.race(
                lambda: access.approve_link_request(
                    link_request_id=first.pk, resident_id=resident.pk, actor=self.owner,
                ),
                lambda: access.approve_link_request(
                    link_request_id=second.pk, resident_id=resident.pk, actor=self.owner,
                ),
            )
            self.assert_clean(results)
            self.assertEqual(self.active_links(resident), 1, results)
            self.assertEqual([kind for kind, _ in results].count('ok'), 1, results)

    def test_approving_the_same_request_twice_is_idempotent(self):
        for _round in range(ROUNDS):
            resident = self.new_resident()
            request = self.new_request(self.alice)
            call = lambda: access.approve_link_request(  # noqa: E731
                link_request_id=request.pk, resident_id=resident.pk, actor=self.owner,
            )
            results = self.race(call, call)
            self.assert_clean(results)
            self.assertEqual(self.active_links(resident), 1, results)
            outcomes = [value for kind, value in results if kind == 'ok']
            self.assertEqual(len(outcomes), 2, results)
            self.assertEqual(outcomes[0][0].pk, outcomes[1][0].pk)
            self.assertEqual(sorted(created for _access, created in outcomes), [False, True])

    def test_accepting_the_same_invite_twice_is_idempotent(self):
        for _round in range(ROUNDS):
            resident = self.new_resident()
            token = self.invite_token(resident)
            call = lambda: access.accept_invite(user=self.ravi, token=token)  # noqa: E731
            results = self.race(call, call)
            self.assert_clean(results)
            self.assertEqual(self.active_links(resident), 1, results)
            outcomes = [value for kind, value in results if kind == 'ok']
            self.assertEqual(len(outcomes), 2, results)
            self.assertEqual(outcomes[0][0].pk, outcomes[1][0].pk)

    def test_revoking_while_accepting_leaves_a_consistent_state(self):
        for _round in range(ROUNDS):
            resident = self.new_resident()
            token = self.invite_token(resident)
            results = self.race(
                lambda: access.accept_invite(user=self.ravi, token=token),
                lambda: access.revoke_access(resident_id=resident.pk, actor=self.owner),
            )
            self.assert_clean(results)
            with tenant_context(self.tenant.id):
                rows = list(ResidentAccess.objects.filter(resident=resident))
            self.assertLessEqual(len([row for row in rows if row.status == 'active']), 1)
            # Whichever won, an accepted invite points at the link it created.
            with tenant_context(self.tenant.id):
                invite = ResidentInvite.objects.get(resident=resident)
            if invite.status == ResidentInvite.Status.ACCEPTED:
                self.assertEqual(len(rows), 1)
                self.assertEqual(invite.resulting_access_id, rows[0].pk)

    def test_leaving_while_a_link_is_granted_starts_the_clock_exactly_once(self):
        for _round in range(ROUNDS):
            resident = self.new_resident()
            request = self.new_request(self.alice)
            results = self.race(
                lambda: access.approve_link_request(
                    link_request_id=request.pk, resident_id=resident.pk, actor=self.owner,
                ),
                lambda: self._leave(resident),
            )
            for kind, value in results:
                if kind == 'error':
                    # Losing the race is fine, if it loses cleanly: the record had already left.
                    self.assertIsInstance(value, access.ResidentNotEligible, repr(value))
            with tenant_context(self.tenant.id):
                rows = list(ResidentAccess.objects.filter(resident=resident))
            self.assertLessEqual(len(rows), 1)
            for row in rows:
                # Whenever a link exists the exit has stamped it, whichever ran first.
                self.assertIsNotNone(row.exited_at, results)
                self.assertIsNotNone(row.access_expires_at, results)
                self.assertGreater(row.access_expires_at, row.exited_at)

    def _leave(self, resident):
        with transaction.atomic():
            locked = access.lock_resident_row(resident.pk)
            locked.status = Resident.Status.VACATED
            locked.save(update_fields=['status', 'updated_at'])
            access.record_exit(locked)
        return locked
