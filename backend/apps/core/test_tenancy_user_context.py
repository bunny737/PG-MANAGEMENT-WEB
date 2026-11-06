"""app.user_id (Module 26): the third tenancy GUC, saved, restored and cleared with the other two."""
from datetime import timedelta
from unittest import mock
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, User
from apps.accounts.serializers import LoginSerializer
from apps.core.roles import Role
from apps.core.tenancy import _current_context, clear_tenant_context, set_tenant_context, tenant_context


def blank(value):
    return value or None


def current():
    tenant, super_admin, user = _current_context()
    return blank(tenant), blank(super_admin), blank(user)


class UserContextTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='T', trial_ends_at=timezone.now() + timedelta(days=30))
        self.user_id = uuid4()

    def test_set_and_clear_cover_all_three(self):
        set_tenant_context(self.tenant.id, True, self.user_id)
        self.assertEqual(current(), (str(self.tenant.id), 'true', str(self.user_id)))
        clear_tenant_context()
        self.assertEqual(current(), (None, None, None))

    def test_entering_a_tenant_keeps_the_callers_identity(self):
        set_tenant_context(None, False, self.user_id)
        with tenant_context(self.tenant.id):
            self.assertEqual(current(), (str(self.tenant.id), None, str(self.user_id)))
        # ... and the whole previous context comes back.
        self.assertEqual(current(), (None, None, str(self.user_id)))

    def test_nesting_restores_each_level(self):
        set_tenant_context(None, False, self.user_id)
        other = Tenant.objects.create(name='U', trial_ends_at=timezone.now() + timedelta(days=30))
        with tenant_context(self.tenant.id):
            with tenant_context(other.id):
                self.assertEqual(current()[0], str(other.id))
                self.assertEqual(current()[2], str(self.user_id))
            self.assertEqual(current()[0], str(self.tenant.id))
        self.assertEqual(current(), (None, None, str(self.user_id)))

    def test_an_explicit_none_drops_the_identity_and_it_returns_afterwards(self):
        set_tenant_context(self.tenant.id, False, self.user_id)
        with tenant_context(self.tenant.id, user_id=None):
            self.assertIsNone(current()[2])
        self.assertEqual(current()[2], str(self.user_id))

    def test_an_exception_inside_still_restores(self):
        set_tenant_context(None, False, self.user_id)
        with self.assertRaises(RuntimeError):
            with tenant_context(self.tenant.id, is_super_admin=True):
                raise RuntimeError('boom')
        self.assertEqual(current(), (None, None, str(self.user_id)))

    def test_the_audit_helper_does_not_drop_the_identity(self):
        # Every service audits inside the person's request; if that cleared app.user_id the
        # user-keyed policies would stop matching mid-request.
        from apps.audit import log as audit_log

        set_tenant_context(self.tenant.id, False, self.user_id)
        audit_log.record(action='test.x', tenant_id=self.tenant.id)
        self.assertEqual(current()[2], str(self.user_id))


class RequestContextTests(TestCase):
    """What authentication puts in the GUCs for each kind of caller, and that nothing lingers."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name='T', trial_ends_at=timezone.now() + timedelta(days=30))
        self.owner = User.objects.create_user(
            email='o@example.com', password='Vintage-Kite-77', tenant=self.tenant, role=Role.OWNER,
            first_name='O', email_verified=True,
        )
        self.person = User.objects.create_user(
            email='p@example.com', password='Vintage-Kite-77', tenant=None, role=Role.RESIDENT,
            first_name='P', email_verified=True,
        )
        self.client = APIClient()

    def call_as(self, user, url_name):
        token = LoginSerializer.get_token(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        return self.client.get(reverse(url_name))

    def test_a_resident_request_carries_only_its_identity_and_the_middleware_clears_it(self):
        from apps.residents import access_views

        seen = {}
        original = access_views.MyResidenciesView.get

        def spy(view, request):
            seen['ctx'] = current()
            return original(view, request)

        with mock.patch.object(access_views.MyResidenciesView, 'get', spy):
            self.assertEqual(self.call_as(self.person, 'my-residencies').status_code, 200)
        self.assertEqual(seen['ctx'], (None, None, str(self.person.pk)))
        self.assertEqual(current(), (None, None, None))

    def test_a_staff_request_never_sets_a_user_id(self):
        from apps.accounts import views

        seen = {}
        original = views.MeView.get

        def spy(view, request, *args, **kwargs):
            seen['ctx'] = current()
            return original(view, request, *args, **kwargs)

        with mock.patch.object(views.MeView, 'get', spy):
            self.assertEqual(self.call_as(self.owner, 'auth-me').status_code, 200)
        tenant, _super_admin, user = seen['ctx']
        self.assertEqual(tenant, str(self.tenant.id))
        self.assertIsNone(user)
        self.assertEqual(current(), (None, None, None))
