"""Row-Level Security proofs for resident app access (invariant 1, Module 26).

Three tables are about a PG's record AND a tenant-less person. `resident_access` and
`residency_link_requests` let that person SELECT their own rows through `app.user_id`; every write
is tenant-only, so the person can never update, delete or insert through the user clause. The
invite has no person column at all and uses the standard tenant policy. These tests go straight
to the database layer, as the runtime (non-superuser) role."""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.residents.models import ResidencyLinkRequest, Resident, ResidentAccess, ResidentInvite

from .test_app_access import AppAccessTestCase


class AppAccessRlsTests(AppAccessTestCase):
    def setUp(self):
        super().setUp()
        self.bob = self.create_account('bob@example.com')
        self.carol = self.create_account('carol@example.com')
        self.alice_link = self.grant(self.alice, self.resident)
        second = self.create_resident(self.prop, first_name='Sita', phone='9000000020', status=Resident.Status.ACTIVE)
        self.bob_link = self.grant(self.bob, second)
        foreign = self.create_resident(
            self.other_prop, first_name='Ravi', phone='9000000021', status=Resident.Status.ACTIVE,
        )
        self.carol_link = self.grant(self.carol, foreign)
        with tenant_context(self.tenant.id):
            self.alice_request = ResidencyLinkRequest.objects.create(
                tenant_id=self.tenant.id, requester=self.alice, property=self.prop,
            )
            self.bob_request = ResidencyLinkRequest.objects.create(
                tenant_id=self.tenant.id, requester=self.bob, property=self.prop,
            )
            self.invite = ResidentInvite.objects.create(
                tenant_id=self.tenant.id, resident=self.resident, email='ravi@example.com',
                expires_at=timezone.now() + timedelta(days=1),
            )

    # --- reading ---
    def test_a_person_reads_only_their_own_links_and_requests(self):
        with tenant_context(None, user_id=self.alice.pk):
            self.assertEqual([x.pk for x in ResidentAccess.objects.all()], [self.alice_link.pk])
            self.assertEqual([x.pk for x in ResidencyLinkRequest.objects.all()], [self.alice_request.pk])

    def test_a_tenant_sees_all_its_own_rows_and_none_of_anothers(self):
        with tenant_context(self.tenant.id):
            self.assertEqual(
                {x.pk for x in ResidentAccess.objects.all()}, {self.alice_link.pk, self.bob_link.pk},
            )
        with tenant_context(self.other_tenant.id):
            self.assertEqual([x.pk for x in ResidentAccess.objects.all()], [self.carol_link.pk])
            self.assertEqual(ResidencyLinkRequest.objects.count(), 0)
            self.assertEqual(ResidentInvite.objects.count(), 0)

    def test_no_context_reads_nothing(self):
        self.assertEqual(ResidentAccess.objects.count(), 0)
        self.assertEqual(ResidencyLinkRequest.objects.count(), 0)
        self.assertEqual(ResidentInvite.objects.count(), 0)

    def test_the_invite_is_invisible_to_a_person_and_to_other_tenants(self):
        with tenant_context(None, user_id=self.alice.pk):
            self.assertEqual(ResidentInvite.objects.count(), 0)
        with tenant_context(self.other_tenant.id):
            self.assertEqual(ResidentInvite.objects.count(), 0)
        with tenant_context(self.tenant.id):
            self.assertEqual(ResidentInvite.objects.count(), 1)

    # --- the user clause is SELECT-only ---
    def test_a_person_cannot_update_or_delete_their_own_rows(self):
        with tenant_context(None, user_id=self.alice.pk):
            self.assertEqual(ResidentAccess.objects.filter(pk=self.alice_link.pk).update(status='revoked'), 0)
            self.assertEqual(ResidentAccess.objects.filter(pk=self.alice_link.pk).delete()[0], 0)
            self.assertEqual(
                ResidencyLinkRequest.objects.filter(pk=self.alice_request.pk).update(status='approved'), 0,
            )
            self.assertEqual(ResidencyLinkRequest.objects.filter(pk=self.alice_request.pk).delete()[0], 0)
        with tenant_context(self.tenant.id):
            self.assertEqual(ResidentAccess.objects.get(pk=self.alice_link.pk).status, 'active')
            self.assertTrue(ResidencyLinkRequest.objects.filter(pk=self.alice_request.pk, status='pending').exists())

    def test_a_person_cannot_insert_a_link_for_themselves(self):
        with tenant_context(None, user_id=self.alice.pk):
            with self.assertRaises(DatabaseError), transaction.atomic():
                ResidentAccess.objects.create(
                    tenant_id=self.tenant.id, user=self.alice, resident=self.resident,
                    origin='invite', activated_at=timezone.now(),
                )

    def test_a_person_cannot_insert_a_request_without_a_tenant(self):
        with tenant_context(None, user_id=self.alice.pk):
            with self.assertRaises(DatabaseError), transaction.atomic():
                ResidencyLinkRequest.objects.create(
                    tenant_id=self.tenant.id, requester=self.alice, property=self.other_prop,
                )

    def test_one_tenant_cannot_write_to_anothers_rows(self):
        with tenant_context(self.other_tenant.id):
            self.assertEqual(ResidentAccess.objects.filter(pk=self.alice_link.pk).update(status='revoked'), 0)
            self.assertEqual(ResidentAccess.objects.filter(pk=self.alice_link.pk).delete()[0], 0)
            with self.assertRaises(DatabaseError), transaction.atomic():
                ResidentAccess.objects.create(
                    tenant_id=self.tenant.id, user=self.alice, resident=self.resident,
                    origin='invite', activated_at=timezone.now(),
                )

    def test_a_user_id_alongside_another_tenant_still_opens_select_only(self):
        # Defence in depth: even with app.user_id set on a tenant request, writes stay tenant-only.
        with tenant_context(self.other_tenant.id, user_id=self.alice.pk):
            self.assertEqual(ResidentAccess.objects.filter(pk=self.alice_link.pk).update(status='revoked'), 0)

    # --- composite foreign keys ---
    def test_a_link_cannot_name_another_tenants_record(self):
        # Tenant B writes a row with its own tenant_id but tenant A's resident: the RLS check
        # passes, the (resident_id, tenant_id) foreign key does not.
        with tenant_context(self.other_tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ResidentAccess.objects.create(
                    tenant_id=self.other_tenant.id, user=self.alice, resident=self.resident,
                    origin='invite', activated_at=timezone.now(),
                )
            with self.assertRaises(IntegrityError), transaction.atomic():
                ResidentInvite.objects.create(
                    tenant_id=self.other_tenant.id, resident=self.resident, email='x@example.com',
                    expires_at=timezone.now(),
                )

    # --- constraints ---
    def test_one_active_link_per_record_is_a_database_rule(self):
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ResidentAccess.objects.create(
                    tenant_id=self.tenant.id, user=self.carol, resident=self.resident,
                    origin='invite', activated_at=timezone.now(),
                )

    def test_one_pending_invite_per_record_is_a_database_rule(self):
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ResidentInvite.objects.create(
                    tenant_id=self.tenant.id, resident=self.resident, email='ravi@example.com',
                    expires_at=timezone.now(),
                )

    def test_one_pending_request_per_person_and_property_is_a_database_rule(self):
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ResidencyLinkRequest.objects.create(
                    tenant_id=self.tenant.id, requester=self.alice, property=self.prop,
                )

    def test_the_fixture_people_are_tenantless_residents(self):
        self.assertIsNone(self.alice.tenant_id)
        self.assertEqual(self.alice.role, Role.RESIDENT)
