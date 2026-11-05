"""Resident app access lifecycle (Module 26): staff invites, link requests by join code, approval,
revocation, the post-exit window, and the scope check. See docs/modules/26-resident-identity.md.

A Resident (the PG's record) needs no login. A person's own resident-pool account is linked to it
only by accepting an invite or by staff approving a request; nothing here ever creates a User."""
from datetime import timedelta
from types import SimpleNamespace

from django.core import mail
from django.test import override_settings
from django.urls import path, reverse
from django.utils import timezone
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.models import PlatformConfig
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.properties.join_codes import ALPHABET, LENGTH
from apps.properties.models import Property
from apps.residents import access
from apps.residents.access import ResidencyScopedAPIView, Scope, residency_scope
from apps.residents.models import ResidencyLinkRequest, Resident, ResidentAccess, ResidentInvite

from .base import ResidentAPITestCase

ACTIVE = Resident.Status.ACTIVE


class AppAccessTestCase(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.other_tenant = self.create_tenant('Other PG')
        self.other_owner = self.create_owner(self.other_tenant, email='other-owner@example.com')
        self.other_prop = self.create_property(self.other_tenant, name='Other PG - Kondapur')
        self.resident = self.create_resident(self.prop, email='ravi@example.com', status=ACTIVE)
        self.alice = self.create_account('alice@example.com')

    # --- fixtures ---
    def create_account(self, email, **kwargs):
        return self.create_user(None, Role.RESIDENT, email, **kwargs)

    def grant(self, user, resident, **kwargs):
        kwargs.setdefault('origin', ResidentAccess.Origin.INVITE)
        kwargs.setdefault('activated_at', timezone.now())
        with tenant_context(resident.tenant_id):
            return ResidentAccess.objects.create(
                tenant_id=resident.tenant_id, user=user, resident=resident, **kwargs,
            )

    def set_status(self, resident, status):
        with tenant_context(resident.tenant_id):
            Resident.objects.filter(pk=resident.pk).update(status=status)
        resident.status = status

    def as_staff(self, user=None):
        self.authenticate(user or self.owner)

    def as_person(self, user=None):
        self.authenticate(user or self.alice)

    def send_invite(self, resident=None):
        self.as_staff()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('resident-app-invite', args=[(resident or self.resident).pk]))

    def token_from_last_mail(self):
        return self.extract_query_param(mail.outbox[-1].body, 'token')

    def accept(self, token, user=None):
        self.as_person(user)
        return self.client.post(reverse('my-invite-accept'), {'token': token})

    def links(self, resident=None):
        with tenant_context(self.tenant.id, user_id=None):
            return list(ResidentAccess.objects.filter(resident=resident or self.resident))

    def fresh(self, obj):
        with tenant_context(obj.tenant_id):
            return type(obj).objects.get(pk=obj.pk)


# --------------------------------------------------------------------------------------------
class ScopeTests(AppAccessTestCase):
    """residency_scope() on in-memory objects: the rules, in precedence order."""

    def link(self, **kwargs):
        defaults = dict(status='active', access_expires_at=None)
        return SimpleNamespace(**{**defaults, **kwargs})

    def res(self, status):
        return SimpleNamespace(status=status)

    def test_living_resident_gets_full_scope(self):
        for status in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
            self.assertEqual(residency_scope(self.link(), self.res(status), 'active'), Scope.FULL)

    def test_reserved_resident_gets_the_reserved_scope(self):
        self.assertEqual(residency_scope(self.link(), self.res(Resident.Status.RESERVED), 'active'), Scope.RESERVED)

    def test_an_inquiry_is_a_lead_not_a_resident(self):
        self.assertEqual(residency_scope(self.link(), self.res(Resident.Status.INQUIRY), 'active'), Scope.NONE)

    def test_exited_resident_gets_bills_only_until_the_expiry(self):
        future = timezone.now() + timedelta(days=1)
        for status in access.EXIT_STATUSES:
            self.assertEqual(
                residency_scope(self.link(access_expires_at=future), self.res(status), 'active'), Scope.BILLS,
            )

    def test_access_ends_at_the_timestamp_without_any_background_job(self):
        past = timezone.now() - timedelta(seconds=1)
        self.assertEqual(
            residency_scope(self.link(access_expires_at=past), self.res(Resident.Status.VACATED), 'active'),
            Scope.NONE,
        )

    def test_an_exit_that_never_stamped_an_expiry_fails_closed(self):
        self.assertEqual(
            residency_scope(self.link(), self.res(Resident.Status.VACATED), 'active'), Scope.NONE,
        )

    def test_revoked_or_expired_link_is_denied_whatever_the_resident_status(self):
        for status in ('revoked', 'expired'):
            self.assertEqual(
                residency_scope(self.link(status=status), self.res(ACTIVE), 'active'), Scope.NONE,
            )

    def test_a_suspended_tenant_narrows_full_access_to_bills(self):
        for tenant_status in ('suspended', 'cancelled'):
            self.assertEqual(residency_scope(self.link(), self.res(ACTIVE), tenant_status), Scope.BILLS)

    def test_a_suspended_tenant_never_revives_an_expired_link(self):
        past = timezone.now() - timedelta(days=1)
        self.assertEqual(
            residency_scope(self.link(access_expires_at=past), self.res(Resident.Status.VACATED), 'suspended'),
            Scope.NONE,
        )
        self.assertEqual(residency_scope(self.link(status='revoked'), self.res(ACTIVE), 'suspended'), Scope.NONE)

    def test_a_deleted_tenant_grants_nothing(self):
        self.assertEqual(residency_scope(self.link(), self.res(ACTIVE), 'deleted'), Scope.NONE)

    def test_scope_ranking(self):
        self.assertTrue(Scope.allows(Scope.FULL, Scope.BILLS))
        self.assertTrue(Scope.allows(Scope.RESERVED, Scope.RESERVED))
        self.assertFalse(Scope.allows(Scope.BILLS, Scope.RESERVED))
        self.assertFalse(Scope.allows(Scope.RESERVED, Scope.FULL))
        self.assertFalse(Scope.allows(Scope.NONE, Scope.BILLS))


# --------------------------------------------------------------------------------------------
class InviteTests(AppAccessTestCase):
    def test_sending_an_invite_emails_the_record_address_and_creates_no_user(self):
        users_before = User.objects.count()
        response = self.send_invite()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ravi@example.com'])
        self.assertTrue(self.token_from_last_mail())
        self.assertTrue(response.data['invite']['status'] == 'pending')

    def test_the_token_is_hashed_and_never_stored_in_clear(self):
        self.send_invite()
        token = self.token_from_last_mail()
        with tenant_context(self.tenant.id):
            invite = ResidentInvite.objects.get(resident=self.resident)
        self.assertNotIn(invite.token_hash, token)
        self.assertEqual(len(invite.token_hash), 64)

    def test_a_resident_without_an_email_cannot_be_invited_but_works_normally(self):
        bare = self.create_resident(self.prop, first_name='Sita', phone='9000000002', status=ACTIVE)
        response = self.send_invite(bare)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'RESIDENT_EMAIL_REQUIRED')
        self.assertEqual(len(mail.outbox), 0)
        self.as_staff()
        state = self.client.get(reverse('resident-app-access', args=[bare.pk]))
        self.assertEqual(state.status_code, 200)
        self.assertFalse(state.data['can_invite'])

    def test_only_eligible_statuses_can_be_invited(self):
        for status in (Resident.Status.INQUIRY, Resident.Status.VACATED, Resident.Status.BLACKLISTED):
            resident = self.create_resident(
                self.prop, first_name=status, phone='9000000010', email=f'{status}@example.com', status=status,
            )
            self.assertEqual(self.send_invite(resident).status_code, 400, status)

    def test_accepting_links_the_signed_in_person(self):
        self.send_invite()
        # alice's account email must equal the invited address
        ravi = self.create_account('ravi@example.com')
        response = self.accept(self.token_from_last_mail(), ravi)
        self.assertEqual(response.status_code, 201)
        [link] = self.links()
        self.assertEqual(link.user_id, ravi.pk)
        self.assertEqual(link.origin, ResidentAccess.Origin.INVITE)
        self.assertEqual(link.status, ResidentAccess.Status.ACTIVE)
        with tenant_context(self.tenant.id):
            invite = ResidentInvite.objects.get(resident=self.resident)
        self.assertEqual(invite.status, ResidentInvite.Status.ACCEPTED)
        self.assertEqual(invite.resulting_access_id, link.pk)
        self.assertEqual(invite.accepted_by_id, ravi.pk)

    def test_anonymous_accept_is_refused(self):
        self.send_invite()
        self.client.credentials()
        response = self.client.post(reverse('my-invite-accept'), {'token': self.token_from_last_mail()})
        self.assertEqual(response.status_code, 401)

    def test_a_staff_account_cannot_accept(self):
        self.send_invite()
        self.as_staff()
        response = self.client.post(reverse('my-invite-accept'), {'token': self.token_from_last_mail()})
        self.assertEqual(response.status_code, 403)

    def test_an_unverified_account_cannot_accept(self):
        self.send_invite()
        ravi = self.create_account('ravi@example.com', email_verified=False)
        response = self.accept(self.token_from_last_mail(), ravi)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.links(), [])

    def test_a_different_email_cannot_use_a_forwarded_link(self):
        self.send_invite()
        response = self.accept(self.token_from_last_mail(), self.alice)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'INVITE_EMAIL_MISMATCH')
        self.assertEqual(self.links(), [])

    def test_a_tampered_token_is_rejected(self):
        self.send_invite()
        ravi = self.create_account('ravi@example.com')
        token = self.token_from_last_mail()
        tampered = token[:-3] + ('aaa' if not token.endswith('aaa') else 'bbb')
        self.assertEqual(self.accept(tampered, ravi).status_code, 400)
        self.assertEqual(self.accept('garbage', ravi).status_code, 400)
        self.assertEqual(self.links(), [])

    def test_an_expired_invite_is_rejected(self):
        self.send_invite()
        ravi = self.create_account('ravi@example.com')
        with tenant_context(self.tenant.id):
            ResidentInvite.objects.filter(resident=self.resident).update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.accept(self.token_from_last_mail(), ravi)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'INVITE_INVALID')

    def test_a_resend_voids_the_earlier_link(self):
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        first = self.token_from_last_mail()
        self.send_invite()
        second = self.token_from_last_mail()
        self.assertNotEqual(first, second)
        self.assertEqual(self.accept(first, ravi).status_code, 400)
        self.assertEqual(self.accept(second, ravi).status_code, 201)

    def test_cancelling_voids_the_link_and_is_idempotent(self):
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        token = self.token_from_last_mail()
        self.as_staff()
        url = reverse('resident-app-invite-cancel', args=[self.resident.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.accept(token, ravi).status_code, 400)

    def test_retrying_returns_the_same_link(self):
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        token = self.token_from_last_mail()
        first = self.accept(token, ravi)
        again = self.accept(token, ravi)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.data['residency_id'], again.data['residency_id'])
        self.assertEqual(len(self.links()), 1)

    def test_retry_after_revoke_never_reactivates_access(self):
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        token = self.token_from_last_mail()
        self.accept(token, ravi)
        self.as_staff()
        self.client.post(reverse('resident-app-access-revoke', args=[self.resident.pk]))
        again = self.accept(token, ravi)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['status'], 'revoked')
        self.assertEqual([link.status for link in self.links()], ['revoked'])

    def test_another_person_cannot_replay_an_accepted_token(self):
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        token = self.token_from_last_mail()
        self.accept(token, ravi)
        self.assertEqual(self.accept(token, self.alice).status_code, 400)

    def test_a_resident_who_is_no_longer_eligible_cannot_be_joined(self):
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        token = self.token_from_last_mail()
        self.set_status(self.resident, Resident.Status.VACATED)
        self.assertEqual(self.accept(token, ravi).status_code, 400)
        self.assertEqual(self.links(), [])

    def test_two_pgs_can_invite_the_same_email_and_one_account_holds_both_links(self):
        ravi = self.create_account('ravi@example.com')
        other = self.create_resident(self.other_prop, first_name='Ravi', phone='9000000003',
                                     email='ravi@example.com', status=ACTIVE)
        self.send_invite()
        first = self.token_from_last_mail()
        self.as_staff(self.other_owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('resident-app-invite', args=[other.pk]))
        second = self.token_from_last_mail()
        self.assertEqual(self.accept(first, ravi).status_code, 201)
        self.assertEqual(self.accept(second, ravi).status_code, 201)
        self.as_person(ravi)
        rows = self.client.get(reverse('my-residencies')).data
        self.assertEqual(len(rows), 2)

    def test_signup_login_and_reset_never_activate_a_link(self):
        self.send_invite()
        self.client.credentials()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('resident-signup'), {
                'email': 'ravi@example.com', 'password': 'Sturdy-Passw0rd-9', 'first_name': 'Ravi',
            })
        self.assertEqual(self.links(), [])

    def test_staff_of_another_tenant_cannot_invite_this_resident(self):
        self.as_staff(self.other_owner)
        response = self.client.post(reverse('resident-app-invite', args=[self.resident.pk]))
        self.assertEqual(response.status_code, 404)

    def test_a_receptionist_cannot_invite(self):
        reception = self.create_receptionist(self.tenant)
        self.assign_staff(reception, self.prop)
        self.as_staff(reception)
        response = self.client.post(reverse('resident-app-invite', args=[self.resident.pk]))
        self.assertEqual(response.status_code, 403)

    def test_a_manager_without_this_property_cannot_invite(self):
        manager = self.create_manager(self.tenant)  # not assigned to self.prop
        self.as_staff(manager)
        response = self.client.post(reverse('resident-app-invite', args=[self.resident.pk]))
        self.assertEqual(response.status_code, 404)

    def test_invite_and_revoke_are_audit_logged(self):
        from apps.audit.models import AuditLog

        self.send_invite()
        self.grant(self.alice, self.resident)
        self.as_staff()
        self.client.post(reverse('resident-app-access-revoke', args=[self.resident.pk]))
        with tenant_context(self.tenant.id):
            actions = set(AuditLog.objects.filter(tenant_id=self.tenant.id).values_list('action', flat=True))
        self.assertIn('resident.app_invite_sent', actions)
        self.assertIn('resident.app_access_revoked', actions)


# --------------------------------------------------------------------------------------------
class JoinCodeTests(AppAccessTestCase):
    def test_every_property_gets_a_random_code_from_the_safe_alphabet(self):
        codes = {self.prop.join_code, self.other_prop.join_code}
        self.assertEqual(len(codes), 2)
        for code in codes:
            self.assertEqual(len(code), LENGTH)
            self.assertTrue(set(code) <= set(ALPHABET))

    def lookup(self, code, user=None):
        self.as_person(user)
        return self.client.get(reverse('my-join-code-lookup', args=[code]))

    def test_lookup_returns_only_the_name_and_city(self):
        response = self.lookup(self.prop.join_code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'name', 'city'})
        self.assertEqual(response.data['name'], self.prop.name)

    def test_lookup_is_case_and_separator_insensitive(self):
        code = self.prop.join_code
        self.assertEqual(self.lookup(f'{code[:4].lower()}-{code[4:].lower()}').status_code, 200)

    def test_unknown_malformed_and_blocked_codes_all_look_alike(self):
        self.assertEqual(self.lookup('ABCDEFGH').status_code, 404)
        self.assertEqual(self.lookup('short').status_code, 404)
        self.assertEqual(self.lookup('0OIl1111').status_code, 404)
        self.other_tenant.status = 'suspended'
        self.other_tenant.save()
        self.assertEqual(self.lookup(self.other_prop.join_code).status_code, 404)

    def test_an_inactive_property_cannot_be_found(self):
        with tenant_context(self.tenant.id):
            Property.objects.filter(pk=self.prop.pk).update(status=Property.Status.INACTIVE)
        self.assertEqual(self.lookup(self.prop.join_code).status_code, 404)

    def test_lookup_needs_a_verified_resident_account(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get(reverse('my-join-code-lookup', args=[self.prop.join_code])).status_code, 401,
        )
        unverified = self.create_account('new@example.com', email_verified=False)
        self.assertEqual(self.lookup(self.prop.join_code, unverified).status_code, 403)
        self.as_staff()
        self.assertEqual(
            self.client.get(reverse('my-join-code-lookup', args=[self.prop.join_code])).status_code, 403,
        )

    def test_rotation_invalidates_the_old_code_at_once(self):
        old = self.prop.join_code
        self.as_staff()
        response = self.client.post(reverse('property-join-code-rotate', args=[self.prop.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['join_code'], old)
        self.assertEqual(self.lookup(old).status_code, 404)
        self.assertEqual(self.lookup(response.data['join_code']).status_code, 200)

    def test_rotation_needs_edit_rights_on_a_visible_property(self):
        reception = self.create_receptionist(self.tenant)
        self.assign_staff(reception, self.prop)
        self.as_staff(reception)
        url = reverse('property-join-code-rotate', args=[self.prop.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.as_staff(self.other_owner)
        self.assertEqual(self.client.post(url).status_code, 404)

    def lookup_with_rates(self, *, user_rate, ip_rate):
        from unittest import mock

        from rest_framework.throttling import SimpleRateThrottle

        return mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {
            'resident_join_code_lookup': user_rate, 'resident_join_code_lookup_ip': ip_rate,
        })

    def test_lookups_are_throttled_per_user(self):
        bob = self.create_account('bob@example.com')
        with self.lookup_with_rates(user_rate='2/hour', ip_rate='100/hour'):
            self.assertEqual(self.lookup('ABCDEFGH').status_code, 404)
            self.assertEqual(self.lookup('ABCDEFGH').status_code, 404)
            self.assertEqual(self.lookup('ABCDEFGH').status_code, 429)
            # Another account has its own allowance.
            self.assertEqual(self.lookup('ABCDEFGH', bob).status_code, 404)

    def test_lookups_are_throttled_per_address_across_accounts(self):
        bob = self.create_account('bob@example.com')
        with self.lookup_with_rates(user_rate='100/hour', ip_rate='3/hour'):
            for _ in range(3):
                self.assertEqual(self.lookup('ABCDEFGH').status_code, 404)
            # One address using a different account is still refused.
            self.assertEqual(self.lookup('ABCDEFGH', bob).status_code, 429)

    def test_a_join_code_alone_grants_no_access(self):
        self.lookup(self.prop.join_code)
        self.assertEqual(self.links(), [])
        self.as_person()
        self.assertEqual(self.client.get(reverse('my-residencies')).data, [])


# --------------------------------------------------------------------------------------------
class LinkRequestTests(AppAccessTestCase):
    def ask(self, user=None, code=None, **extra):
        self.as_person(user)
        return self.client.post(reverse('my-link-requests'), {'join_code': code or self.prop.join_code, **extra})

    def pending(self):
        with tenant_context(self.tenant.id):
            return list(ResidencyLinkRequest.objects.filter(status='pending'))

    def request_rows(self):
        data = self.client.get(reverse("residency-link-request-list")).data
        return data["results"] if isinstance(data, dict) else data

    def approve(self, link_request_id, resident, user=None):
        self.as_staff(user)
        return self.client.post(
            reverse('residency-link-request-approve', args=[link_request_id]), {'resident_id': str(resident.pk)},
        )

    def test_a_verified_person_can_ask_with_a_join_code(self):
        response = self.ask(message='Room 204', claimed_name='Ravi Kumar', claimed_room='204')
        self.assertEqual(response.status_code, 201)
        [pending] = self.pending()
        self.assertEqual(pending.requester_id, self.alice.pk)
        self.assertEqual(pending.property_id, self.prop.pk)
        self.assertEqual(pending.claimed_room, '204')

    def test_asking_again_returns_the_same_request(self):
        first = self.ask()
        again = self.ask()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.data['id'], again.data['id'])
        self.assertEqual(len(self.pending()), 1)

    def test_an_unverified_account_cannot_ask(self):
        unverified = self.create_account('new@example.com', email_verified=False)
        self.assertEqual(self.ask(unverified).status_code, 403)
        self.assertEqual(self.pending(), [])

    def test_an_unknown_code_is_a_generic_404(self):
        self.assertEqual(self.ask(code='ZZZZZZZZ').status_code, 404)

    def test_staff_are_told_and_the_requester_sees_only_their_own_requests(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.ask()
        self.assertTrue(any(self.owner.email in message.to for message in mail.outbox))
        bob = self.create_account('bob@example.com')
        self.as_person(bob)
        self.assertEqual(self.client.get(reverse('my-link-requests')).data, [])
        self.as_person()
        mine = self.client.get(reverse('my-link-requests')).data
        self.assertEqual(len(mine), 1)
        # The property name is read in the PG's own tenant context (the person has none).
        self.assertEqual(mine[0]['property_name'], self.prop.name)

    def test_staff_list_is_limited_to_visible_properties(self):
        self.ask()
        manager = self.create_manager(self.tenant)
        self.as_staff(manager)  # not assigned to self.prop
        self.assertEqual(len(self.request_rows()), 0)
        self.assign_staff(manager, self.prop)
        self.assertEqual(len(self.request_rows()), 1)
        self.as_staff(self.other_owner)
        self.assertEqual(len(self.request_rows()), 0)

    def test_staff_see_possible_matches_but_nothing_is_matched_automatically(self):
        self.ask(claimed_name='Ravi', claimed_phone=self.resident.phone)
        self.as_staff()
        rows = self.request_rows()
        self.assertEqual([m["id"] for m in rows[0]['possible_matches']], [str(self.resident.pk)])
        self.assertEqual(self.links(), [])

    def test_approval_links_the_requester_to_the_chosen_record(self):
        [created] = [self.ask().data]
        response = self.approve(created['id'], self.resident)
        self.assertEqual(response.status_code, 200)
        [link] = self.links()
        self.assertEqual(link.user_id, self.alice.pk)
        self.assertEqual(link.origin, ResidentAccess.Origin.LINK_REQUEST)
        self.assertEqual(link.granted_by_id, self.owner.pk)
        self.as_person()
        [row] = self.client.get(reverse('my-residencies')).data
        self.assertEqual(row['scope'], Scope.FULL)
        self.assertEqual(row['property_name'], self.prop.name)

    def test_the_requester_is_told_the_outcome(self):
        created = self.ask().data
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.approve(created['id'], self.resident)
        self.assertTrue(any('alice@example.com' in message.to for message in mail.outbox))

    def test_retrying_an_approval_returns_the_same_link(self):
        created = self.ask().data
        self.approve(created['id'], self.resident)
        self.assertEqual(self.approve(created['id'], self.resident).status_code, 200)
        self.assertEqual(len(self.links()), 1)

    def test_approving_with_a_different_record_after_approval_conflicts(self):
        created = self.ask().data
        self.approve(created['id'], self.resident)
        second = self.create_resident(self.prop, first_name='Sita', phone='9000000004', status=ACTIVE)
        self.assertEqual(self.approve(created['id'], second).status_code, 409)

    def test_a_record_from_another_property_is_refused(self):
        created = self.ask().data
        elsewhere = self.create_resident(self.prop, first_name='Sita', phone='9000000005', status=ACTIVE)
        second_prop = self.create_property(self.tenant, name='Sunrise PG - Gachibowli')
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=elsewhere.pk).update(property=second_prop)
        response = self.approve(created['id'], elsewhere)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'RESIDENT_PROPERTY_MISMATCH')
        self.assertEqual(self.links(elsewhere), [])

    def test_a_record_from_another_tenant_is_invisible(self):
        created = self.ask().data
        foreign = self.create_resident(self.other_prop, first_name='Ravi', phone='9000000006', status=ACTIVE)
        self.assertEqual(self.approve(created['id'], foreign).status_code, 404)

    def test_a_record_the_staff_member_cannot_see_is_refused(self):
        created = self.ask().data
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        second_prop = self.create_property(self.tenant, name='Sunrise PG - Gachibowli')
        hidden = self.create_resident(second_prop, first_name='Sita', phone='9000000007', status=ACTIVE)
        self.assertEqual(self.approve(created['id'], hidden, manager).status_code, 404)

    def test_an_ineligible_record_is_refused(self):
        created = self.ask().data
        gone = self.create_resident(self.prop, first_name='Sita', phone='9000000008', status=Resident.Status.VACATED)
        self.assertEqual(self.approve(created['id'], gone).status_code, 400)

    def test_a_record_that_already_has_app_access_conflicts(self):
        created = self.ask().data
        bob = self.create_account('bob@example.com')
        self.grant(bob, self.resident)
        self.assertEqual(self.approve(created['id'], self.resident).status_code, 409)

    def test_rejection_is_recorded_and_the_person_may_ask_again(self):
        created = self.ask().data
        self.as_staff()
        response = self.client.post(
            reverse('residency-link-request-reject', args=[created['id']]), {'note': 'Not a resident here'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'rejected')
        self.assertEqual(self.ask().status_code, 201)
        self.assertEqual(self.links(), [])

    def test_the_requester_can_withdraw_but_nobody_else_can(self):
        created = self.ask().data
        bob = self.create_account('bob@example.com')
        self.as_person(bob)
        self.assertEqual(self.client.post(reverse('my-link-request-cancel', args=[created['id']])).status_code, 404)
        self.as_person()
        self.assertEqual(self.client.post(reverse('my-link-request-cancel', args=[created['id']])).status_code, 200)
        self.assertEqual(self.client.post(reverse('my-link-request-cancel', args=[created['id']])).status_code, 200)
        self.assertEqual(self.pending(), [])

    def test_approving_cancels_a_pending_invite_for_the_record(self):
        self.send_invite()
        created = self.ask().data
        self.approve(created['id'], self.resident)
        with tenant_context(self.tenant.id):
            invite = ResidentInvite.objects.get(resident=self.resident)
        self.assertEqual(invite.status, ResidentInvite.Status.CANCELLED)
        self.assertEqual(invite.cancel_reason, ResidentInvite.CancelReason.ACCESS_GRANTED)

    def test_accepting_an_invite_resolves_only_the_accepters_own_request(self):
        ravi = self.create_account('ravi@example.com')
        bob = self.create_account('bob@example.com')
        mine = self.ask(ravi).data
        theirs = self.ask(bob).data
        self.send_invite()
        self.accept(self.token_from_last_mail(), ravi)
        with tenant_context(self.tenant.id):
            statuses = {r.pk.hex: r.status for r in ResidencyLinkRequest.objects.all()}
        self.assertEqual(statuses[mine['id'].replace('-', '')], 'cancelled')
        self.assertEqual(statuses[theirs['id'].replace('-', '')], 'pending')

    def test_a_requester_already_linked_to_the_pg_cannot_ask_again(self):
        self.grant(self.alice, self.resident)
        self.assertEqual(self.ask().status_code, 409)


# --------------------------------------------------------------------------------------------
class RevocationAndExitTests(AppAccessTestCase):
    def setUp(self):
        super().setUp()
        self.link = self.grant(self.alice, self.resident)

    def residency(self):
        self.as_person()
        [row] = self.client.get(reverse('my-residencies')).data
        return row

    def test_revoking_ends_access_and_a_fresh_login_does_not_help(self):
        self.as_staff()
        self.assertEqual(self.client.post(reverse('resident-app-access-revoke', args=[self.resident.pk])).status_code, 200)
        row = self.residency()
        self.assertEqual(row['status'], 'revoked')
        self.assertEqual(row['scope'], Scope.NONE)

    def test_revoking_twice_is_fine(self):
        self.as_staff()
        url = reverse('resident-app-access-revoke', args=[self.resident.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)

    def test_revoking_leaves_other_pgs_untouched(self):
        other = self.create_resident(self.other_prop, first_name='Ravi', phone='9000000009', status=ACTIVE)
        self.grant(self.alice, other)
        self.as_staff()
        self.client.post(reverse('resident-app-access-revoke', args=[self.resident.pk]))
        self.as_person()
        scopes = {row['property_name']: row['scope'] for row in self.client.get(reverse('my-residencies')).data}
        self.assertEqual(scopes[self.prop.name], Scope.NONE)
        self.assertEqual(scopes[self.other_prop.name], Scope.FULL)

    def test_a_reinvite_after_revoking_needs_a_new_acceptance(self):
        self.as_staff()
        self.client.post(reverse('resident-app-access-revoke', args=[self.resident.pk]))
        ravi = self.create_account('ravi@example.com')
        self.send_invite()
        self.assertEqual(self.accept(self.token_from_last_mail(), ravi).status_code, 201)

    def exit_via_status_endpoint(self, resident, *statuses):
        self.as_staff()
        for status in statuses:
            response = self.client.patch(reverse('resident-status', args=[resident.pk]), {'status': status})
            self.assertEqual(response.status_code, 200, response.data)

    def test_vacating_starts_the_post_exit_window_from_platform_config(self):
        config = PlatformConfig.get()
        config.resident_post_exit_access_days = 30
        config.save()
        self.exit_via_status_endpoint(self.resident, 'notice_period', 'vacated')
        link = self.fresh(self.link)
        self.assertIsNotNone(link.exited_at)
        self.assertEqual(link.access_expires_at, link.exited_at + timedelta(days=30))
        self.assertEqual(self.residency()['scope'], Scope.BILLS)

    def test_access_ends_at_the_expiry_with_no_job_running(self):
        self.exit_via_status_endpoint(self.resident, 'notice_period', 'vacated')
        with tenant_context(self.tenant.id):
            ResidentAccess.objects.filter(pk=self.link.pk).update(access_expires_at=timezone.now() - timedelta(seconds=1))
        row = self.residency()
        self.assertEqual(row['status'], 'active')  # nothing has tidied it
        self.assertEqual(row['scope'], Scope.NONE)

    def test_absconded_then_blacklisted_does_not_restart_or_extend_the_clock(self):
        self.exit_via_status_endpoint(self.resident, 'absconded')
        first = self.fresh(self.link)
        self.exit_via_status_endpoint(self.resident, 'blacklisted')
        second = self.fresh(self.link)
        self.assertEqual(first.exited_at, second.exited_at)
        self.assertEqual(first.access_expires_at, second.access_expires_at)

    def test_leaving_withdraws_a_pending_invite(self):
        bare = self.create_resident(self.prop, first_name='Sita', phone='9000000011',
                                    email='sita@example.com', status=Resident.Status.NOTICE_PERIOD)
        self.send_invite(bare)
        self.exit_via_status_endpoint(bare, 'vacated')
        with tenant_context(self.tenant.id):
            invite = ResidentInvite.objects.get(resident=bare)
        self.assertEqual(invite.status, ResidentInvite.Status.CANCELLED)
        self.assertEqual(invite.cancel_reason, ResidentInvite.CancelReason.RESIDENT_LEFT)

    def test_a_suspended_owner_narrows_the_residents_view_to_bills(self):
        self.tenant.status = 'suspended'
        self.tenant.save()
        self.assertEqual(self.residency()['scope'], Scope.BILLS)

    def test_the_staff_card_shows_the_current_state(self):
        self.as_staff()
        state = self.client.get(reverse('resident-app-access', args=[self.resident.pk])).data
        self.assertTrue(state['eligible'])
        self.assertFalse(state['can_invite'])  # already has access
        self.assertEqual(state['access']['status'], 'active')
        self.assertEqual(state['access']['account_name'], 'Test')


# --------------------------------------------------------------------------------------------
class ProbeView(ResidencyScopedAPIView):
    required_scope = Scope.FULL

    def get(self, request):
        return Response({'resident': str(self.resident.pk), 'scope': self.scope})


class BillsProbeView(ResidencyScopedAPIView):
    required_scope = Scope.BILLS

    def get(self, request):
        return Response({'scope': self.scope})


urlpatterns = [
    path('probe/', ProbeView.as_view()),
    path('bills-probe/', BillsProbeView.as_view()),
]


@override_settings(ROOT_URLCONF='apps.residents.tests.test_app_access')
class ResidencyHeaderTests(AppAccessTestCase):
    """The X-Residency-Id mechanism that Module 26b's endpoints build on."""

    def call(self, url='/probe/', residency=None, user=None):
        self.as_person(user)
        extra = {'HTTP_X_RESIDENCY_ID': str(residency.pk)} if residency is not None else {}
        return self.client.get(url, **extra)

    def test_the_header_is_required(self):
        self.grant(self.alice, self.resident)
        response = self.call()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'RESIDENCY_REQUIRED')

    def test_a_valid_link_gets_its_own_record(self):
        link = self.grant(self.alice, self.resident)
        response = self.call(residency=link)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['resident'], str(self.resident.pk))
        self.assertEqual(response.data['scope'], Scope.FULL)

    def test_someone_elses_link_is_refused_like_a_missing_one(self):
        bobs = self.grant(self.create_account('bob@example.com'), self.resident)
        response = self.call(residency=bobs)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'RESIDENCY_NOT_FOUND')
        self.assertEqual(self.call(residency=SimpleNamespace(pk='not-a-uuid')).status_code, 400)

    def test_a_revoked_link_is_refused(self):
        link = self.grant(self.alice, self.resident, status=ResidentAccess.Status.REVOKED)
        response = self.call(residency=link)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'RESIDENCY_INACTIVE')

    def test_the_scope_gates_the_endpoint(self):
        link = self.grant(self.alice, self.resident, access_expires_at=timezone.now() + timedelta(days=5),
                          exited_at=timezone.now())
        self.set_status(self.resident, Resident.Status.VACATED)
        self.assertEqual(self.call('/probe/', link).status_code, 403)
        self.assertEqual(self.call('/bills-probe/', link).status_code, 200)

    def test_a_staff_account_cannot_use_the_header(self):
        link = self.grant(self.alice, self.resident)
        self.authenticate(self.owner)
        response = self.client.get('/probe/', HTTP_X_RESIDENCY_ID=str(link.pk))
        self.assertEqual(response.status_code, 403)
