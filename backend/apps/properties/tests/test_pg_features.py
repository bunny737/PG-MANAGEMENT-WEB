"""Module 18 — PG features. Rule numbers match docs/modules/18-pg-features.md."""
import json
import threading
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TransactionTestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.billing.models import Invoice, InvoiceLineItem
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.properties import feature_services
from apps.properties.feature_catalog import FEATURE_LABELS, match_catalog_code, normalise
from apps.properties.models import FeatureCatalog, Property, PropertyFeature, Room, TenantFeature

from .base import PropertyAPITestCase

FIXTURES = Path(__file__).parent / 'fixtures'


def features_url(prop, building=None):
    url = reverse('property-features', args=[prop.id])
    return f'{url}?building={building.id}' if building else url


class FeatureTestCase(PropertyAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.authenticate(self.owner)

    def replace(self, items=(), building=None, excluded=None, prop=None):
        payload = {'building': str(building.id) if building else None, 'items': list(items)}
        if excluded is not None:
            payload['excluded'] = list(excluded)
        return self.client.post(features_url(prop or self.property), payload, format='json')

    def codes(self, response, key='items'):
        return [item['code'] or item['label'] for item in response.data[key]]

    def audit_entries(self, action='property_features.updated'):
        with tenant_context(self.tenant.id):
            return list(AuditLog.objects.filter(action=action).order_by('created_at'))


class FeatureCatalogTests(FeatureTestCase):
    def test_01_catalogue_is_ordered_by_category_then_display_order(self):
        response = self.client.get(reverse('feature-catalog-list'))

        self.assertEqual(response.status_code, 200)
        keys = [(row['category'], row['display_order']) for row in response.data]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(response.data), FeatureCatalog.objects.count())

    def test_02_catalogue_is_read_only_over_the_api(self):
        url = reverse('feature-catalog-list')
        detail = reverse('feature-catalog-detail', args=[FeatureCatalog.objects.first().id])

        self.assertEqual(self.client.post(url, {'code': 'x'}).status_code, 405)
        self.assertEqual(self.client.patch(detail, {'is_active': False}).status_code, 405)
        self.assertEqual(self.client.delete(detail).status_code, 405)

    def test_03_retired_feature_hidden_from_owner_but_visible_to_super_admin(self):
        FeatureCatalog.objects.filter(code='swimming_pool').update(is_active=False)

        owner_codes = [row['code'] for row in self.client.get(reverse('feature-catalog-list')).data]
        self.authenticate(self.create_super_admin())
        admin_codes = [row['code'] for row in self.client.get(reverse('feature-catalog-list')).data]

        self.assertNotIn('swimming_pool', owner_codes)
        self.assertIn('swimming_pool', admin_codes)

    def test_04_every_seeded_code_has_a_label_and_vice_versa(self):
        self.assertEqual(set(FeatureCatalog.objects.values_list('code', flat=True)), set(FEATURE_LABELS))

    def test_05_labels_follow_accept_language(self):
        url = reverse('feature-catalog-list')

        english = {row['code']: row for row in self.client.get(url).data}
        telugu = {row['code']: row for row in self.client.get(url, HTTP_ACCEPT_LANGUAGE='te').data}

        self.assertEqual(english['wifi']['label'], 'Wi-Fi')
        self.assertEqual(telugu['wifi']['label'], 'వై-ఫై')
        self.assertEqual(telugu['wifi']['category_label'], 'ఇంటర్నెట్ & వినోదం')


class FeatureReplaceTests(FeatureTestCase):
    def test_06_replace_is_a_true_replace(self):
        self.replace([{'code': 'wifi'}, {'code': 'lift'}])

        response = self.replace([{'code': 'wifi'}, {'code': 'gym'}])

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(self.codes(response), ['wifi', 'gym'])

    def test_07_scopes_are_replaced_independently(self):
        block = self.create_building(self.property)
        self.replace([{'code': 'wifi'}])
        self.replace([{'code': 'gym'}], building=block)

        self.replace([{'code': 'lift'}])
        self.assertCountEqual(self.codes(self.client.get(features_url(self.property, block))), ['lift', 'gym'])

        self.replace([], building=block)
        self.assertCountEqual(self.codes(self.client.get(features_url(self.property))), ['lift'])

    def test_08_building_view_tags_inherited_and_own_rows(self):
        block = self.create_building(self.property)
        self.replace([{'code': 'wifi'}])
        self.replace([{'code': 'gym'}], building=block)

        response = self.client.get(features_url(self.property, block))

        sources = {item['code']: item['source'] for item in response.data['items']}
        self.assertEqual(sources, {'wifi': 'property', 'gym': 'building'})
        self.assertEqual(response.data['building'], str(block.id))

    def test_09_building_row_wins_over_property_row(self):
        block = self.create_building(self.property)
        self.replace([{'code': 'laundry_service', 'is_paid': False}])
        self.replace([{'code': 'laundry_service', 'is_paid': True}], building=block)

        items = self.client.get(features_url(self.property, block)).data['items']

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source'], 'building')
        self.assertTrue(items[0]['is_paid'])

    def test_10_unfiltered_get_returns_every_row_at_its_own_scope(self):
        block = self.create_building(self.property)
        self.replace([{'code': 'wifi'}])
        self.replace([{'code': 'gym'}], building=block)

        items = self.client.get(features_url(self.property)).data['items']

        self.assertEqual(
            {(item['code'], item['building']) for item in items},
            {('wifi', None), ('gym', block.id)},
        )

    def test_11_building_of_another_property_is_rejected(self):
        other = self.create_property(self.tenant, name='Other PG')
        other_block = self.create_building(other)

        post = self.replace([{'code': 'wifi'}], building=other_block)
        get = self.client.get(features_url(self.property, other_block))

        self.assertEqual(post.status_code, 400)
        self.assertEqual(post.data['code'], 'BUILDING_NOT_IN_PROPERTY')
        self.assertEqual(get.status_code, 400)

    def test_12_each_item_needs_exactly_one_source(self):
        custom = self.create_tenant_feature(self.tenant)

        both = self.replace([{'code': 'wifi', 'tenant_feature': str(custom.id)}])
        neither = self.replace([{'is_paid': True}])
        unknown = self.replace([{'code': 'no_such_feature'}])

        self.assertEqual(both.data['code'], 'FEATURE_SOURCE_AMBIGUOUS')
        self.assertEqual(neither.data['code'], 'FEATURE_SOURCE_REQUIRED')
        self.assertEqual(unknown.data['code'], 'UNKNOWN_FEATURE')

    def test_13_database_rejects_both_or_neither_feature_source(self):
        custom = self.create_tenant_feature(self.tenant)
        wifi = FeatureCatalog.objects.get(code='wifi')
        with tenant_context(self.tenant.id):
            for kwargs in ({'catalog_feature': wifi, 'tenant_feature': custom}, {}):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    PropertyFeature.objects.create(
                        tenant_id=self.tenant.id, property=self.property, **kwargs,
                    )

    def test_14_duplicate_feature_is_rejected(self):
        response = self.replace([{'code': 'wifi'}, {'code': 'wifi', 'is_paid': True}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'DUPLICATE_FEATURE')

    def test_15_identical_replace_is_a_no_op(self):
        self.replace([{'code': 'wifi'}, {'code': 'gym', 'is_paid': True}])
        with tenant_context(self.tenant.id):
            ids = set(PropertyFeature.objects.values_list('id', flat=True))

        self.replace([{'code': 'gym', 'is_paid': True}, {'code': 'wifi'}])

        with tenant_context(self.tenant.id):
            self.assertEqual(set(PropertyFeature.objects.values_list('id', flat=True)), ids)
        self.assertEqual(len(self.audit_entries()), 1)

    def test_16_empty_items_clears_the_scope(self):
        self.replace([{'code': 'wifi'}])

        response = self.replace([])

        self.assertEqual(response.data['items'], [])

    def test_17_too_many_features_is_rejected(self):
        items = [{'tenant_feature': str(uuid.uuid4())} for _ in range(feature_services.MAX_FEATURES_PER_SCOPE + 1)]

        response = self.replace(items)

        self.assertEqual(response.data['code'], 'TOO_MANY_FEATURES')

    def test_18_paid_flag_never_touches_billing(self):
        self.replace([{'code': 'laundry_service', 'is_paid': True}])

        with tenant_context(self.tenant.id):
            self.assertEqual(Invoice.objects.count(), 0)
            self.assertEqual(InvoiceLineItem.objects.count(), 0)


class FeatureOverrideTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.block = self.create_building(self.property)
        self.replace([{'code': 'wifi'}, {'code': 'lift'}])

    def test_19_building_can_suppress_an_inherited_feature(self):
        response = self.replace([], building=self.block, excluded=[{'code': 'lift'}])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.codes(response), ['wifi'])
        self.assertEqual(self.codes(response, 'excluded'), ['lift'])
        # The PG as a whole still offers it.
        with tenant_context(self.tenant.id):
            self.assertEqual(PropertyFeature.objects.filter(building__isnull=True, is_available=True).count(), 2)

    def test_20_removing_the_suppression_restores_inheritance(self):
        self.replace([], building=self.block, excluded=[{'code': 'lift'}])

        response = self.replace([], building=self.block)

        self.assertCountEqual(self.codes(response), ['wifi', 'lift'])
        self.assertEqual(response.data['excluded'], [])

    def test_21_suppression_is_only_legal_for_a_building(self):
        response = self.replace([{'code': 'wifi'}], excluded=[{'code': 'lift'}])
        nothing = self.replace([], building=self.block, excluded=[{'code': 'gym'}])

        self.assertEqual(response.data['code'], 'SUPPRESSION_REQUIRES_BUILDING')
        self.assertEqual(nothing.data['code'], 'NOTHING_TO_SUPPRESS')
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                PropertyFeature.objects.create(
                    tenant_id=self.tenant.id, property=self.property,
                    catalog_feature=FeatureCatalog.objects.get(code='gym'), is_available=False,
                )

    def test_22_suppression_rows_are_never_paid_and_follow_the_property(self):
        self.replace([], building=self.block, excluded=[{'code': 'lift', 'is_paid': True}])
        with tenant_context(self.tenant.id):
            self.assertFalse(PropertyFeature.objects.get(is_available=False).is_paid)

        # Once the PG stops offering lift there is nothing left to suppress.
        self.replace([{'code': 'wifi'}])

        with tenant_context(self.tenant.id):
            self.assertFalse(PropertyFeature.objects.filter(is_available=False).exists())


class FeatureRetirementTests(FeatureTestCase):
    def test_24_25_retired_feature_stays_visible_and_survives_a_save(self):
        self.replace([{'code': 'wifi'}, {'code': 'gym'}])
        FeatureCatalog.objects.filter(code='gym').update(is_active=False)

        listed = self.client.get(features_url(self.property)).data['items']
        saved = self.replace([{'code': 'wifi', 'is_paid': True}, {'code': 'gym'}])

        self.assertEqual({item['code']: item['is_active'] for item in listed}, {'wifi': True, 'gym': False})
        self.assertEqual(saved.status_code, 200)
        self.assertCountEqual(self.codes(saved), ['wifi', 'gym'])

    def test_26_retired_feature_cannot_be_newly_assigned(self):
        FeatureCatalog.objects.filter(code='gym').update(is_active=False)

        response = self.replace([{'code': 'gym'}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'FEATURE_NOT_ACTIVE')

    def test_27_catalogue_row_in_use_cannot_be_deleted(self):
        self.replace([{'code': 'gym'}])

        with tenant_context(is_super_admin=True):
            with self.assertRaises(ProtectedError):
                FeatureCatalog.objects.get(code='gym').delete()


class FeatureAuditTests(FeatureTestCase):
    def test_28_paid_only_change_is_audited(self):
        self.replace([{'code': 'laundry_service'}])

        self.replace([{'code': 'laundry_service', 'is_paid': True}])

        entries = self.audit_entries()
        self.assertEqual(len(entries), 2)
        self.assertFalse(entries[1].before['items'][0]['is_paid'])
        self.assertTrue(entries[1].after['items'][0]['is_paid'])

    def test_29_audit_entry_records_scope_and_canonical_items(self):
        block = self.create_building(self.property)
        custom = self.create_tenant_feature(self.tenant)

        self.replace([{'code': 'wifi'}, {'tenant_feature': str(custom.id)}], building=block)

        entry = self.audit_entries()[0]
        self.assertEqual(entry.before, {'building': str(block.id), 'items': []})
        self.assertEqual(entry.after['building'], str(block.id))
        self.assertEqual(entry.after['items'], [
            {'type': 'catalog', 'key': 'wifi', 'is_paid': False, 'is_available': True},
            {'type': 'custom', 'key': str(custom.id), 'is_paid': False, 'is_available': True},
        ])
        self.assertEqual(entry.object_id, str(self.property.id))


class TenantFeatureTests(FeatureTestCase):
    def create(self, label, **extra):
        return self.client.post(reverse('tenant-feature-list'), {'label': label}, format='json', **extra)

    def rename(self, feature, label):
        return self.client.patch(
            reverse('tenant-feature-detail', args=[feature.id]), {'label': label}, format='json',
        )

    def test_30_custom_feature_is_reusable_across_properties(self):
        other = self.create_property(self.tenant, name='Other PG')

        created = self.create('Table tennis')
        item = {'tenant_feature': created.data['id']}
        first, second = self.replace([item]), self.replace([item], prop=other)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.codes(first), ['Table tennis'])
        self.assertEqual(self.codes(second), ['Table tennis'])
        self.assertEqual(first.data['items'][0]['category'], 'custom')

    def test_31_same_label_in_other_casing_returns_the_existing_feature(self):
        created = self.create('Table tennis')

        again = self.create('table  TENNIS ')

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['id'], created.data['id'])
        with tenant_context(self.tenant.id):
            self.assertEqual(TenantFeature.objects.count(), 1)
            with self.assertRaises(IntegrityError), transaction.atomic():
                TenantFeature.objects.create(tenant_id=self.tenant.id, label='x', slug='tabletennis')

    def test_32_distinct_telugu_labels_do_not_collide(self):
        first, second = self.create('కిటికీ'), self.create('కటక')

        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertNotEqual(first.data['id'], second.data['id'])

    def test_33_catalogue_duplicates_are_rejected_in_any_locale(self):
        for label, code in [('WiFi', 'wifi'), ('wi fi', 'wifi'), ('Generator', 'power_backup'), ('Lift', 'lift')]:
            for language in ('en', 'te'):
                response = self.create(label, HTTP_ACCEPT_LANGUAGE=language)
                self.assertEqual(response.status_code, 400, label)
                self.assertEqual(response.data['code'], 'FEATURE_IN_GLOBAL_CATALOG')
                self.assertEqual(response.data['catalog_code'], code)

    def test_34_normalisation_matches_the_shared_fixture(self):
        cases = json.loads((FIXTURES / 'feature_normalisation.json').read_text(encoding='utf-8'))

        for case in cases:
            self.assertEqual(normalise(case['input']), case['expected'], case['input'])
        self.assertIsNone(match_catalog_code('Table tennis'))

    def test_35_rename_into_the_catalogue_is_rejected(self):
        feature = self.create_tenant_feature(self.tenant)

        response = self.rename(feature, 'Wi-Fi')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'FEATURE_IN_GLOBAL_CATALOG')

    def test_36_rename_onto_another_custom_feature_is_rejected(self):
        feature = self.create_tenant_feature(self.tenant)
        self.create_tenant_feature(self.tenant, label='Pool table')

        response = self.rename(feature, 'POOL TABLE')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'FEATURE_ALREADY_EXISTS')

    def test_37_rename_is_audited_and_shows_everywhere(self):
        feature = self.create_tenant_feature(self.tenant)
        self.replace([{'tenant_feature': str(feature.id)}])

        response = self.rename(feature, 'TT table')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.codes(self.client.get(features_url(self.property))), ['TT table'])
        entry = self.audit_entries('tenant_feature.updated')[0]
        self.assertEqual((entry.before['label'], entry.after['label']), ('Table tennis', 'TT table'))

    def test_38_another_tenants_custom_feature_is_a_clean_400(self):
        other_tenant = self.create_tenant('Other Tenant')
        foreign = self.create_tenant_feature(other_tenant, label='Sauna')

        response = self.replace([{'tenant_feature': str(foreign.id)}])
        listed = self.client.get(reverse('tenant-feature-list'))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'UNKNOWN_FEATURE')
        self.assertEqual(listed.data, [])

    def test_39_custom_feature_in_use_cannot_be_deleted(self):
        feature = self.create_tenant_feature(self.tenant)
        self.replace([{'tenant_feature': str(feature.id)}])
        url = reverse('tenant-feature-detail', args=[feature.id])

        blocked = self.client.delete(url)
        self.replace([])
        allowed = self.client.delete(url)

        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data['code'], 'FEATURE_IN_USE')
        self.assertEqual(allowed.status_code, 204)

    def test_label_is_required(self):
        response = self.create('  --  ')

        self.assertEqual(response.data['code'], 'FEATURE_LABEL_REQUIRED')


class FeatureDerivedAndAccessTests(FeatureTestCase):
    def test_40_41_derived_reports_room_facts_including_large_sharing(self):
        empty = self.client.get(features_url(self.property)).data['derived']
        floor = self.create_floor(self.property)
        self.create_room(floor, '101', sharing_type=Room.SharingType.SIX, category=Room.Category.AC)
        self.create_room(floor, '102', sharing_type=Room.SharingType.TWO, category=Room.Category.NON_AC)

        derived = self.client.get(features_url(self.property)).data['derived']

        self.assertEqual(empty, {'sharing_types': [], 'room_categories': []})
        self.assertEqual(derived, {'sharing_types': [2, 6], 'room_categories': ['ac', 'non_ac']})

    def test_42_building_scoped_derived_excludes_other_buildings(self):
        self.create_room(self.create_floor(self.property), '101', sharing_type=Room.SharingType.TWO)
        block = self.create_building(self.property)
        with tenant_context(self.tenant.id):
            block_floor = block.floors.create(tenant_id=self.tenant.id, name='Ground Floor', order=0)
        self.create_room(block_floor, '201', sharing_type=Room.SharingType.SIX, category=Room.Category.AC)

        derived = self.client.get(features_url(self.property, block)).data['derived']

        self.assertEqual(derived, {'sharing_types': [6], 'room_categories': ['ac']})

    def test_43_rows_cascade_with_their_property_or_building(self):
        block = self.create_building(self.property)
        self.replace([{'code': 'wifi'}])
        self.replace([{'code': 'gym'}], building=block)

        with tenant_context(self.tenant.id):
            block.delete()
            self.assertEqual(
                list(PropertyFeature.objects.values_list('catalog_feature__code', flat=True)), ['wifi'],
            )
            Property.objects.get(pk=self.property.pk).delete()
            self.assertEqual(PropertyFeature.objects.count(), 0)

    def test_44_role_permissions(self):
        manager = self.create_manager(self.tenant)
        receptionist = self.create_receptionist(self.tenant)
        resident = self.create_user(self.tenant, Role.RESIDENT, 'resident@example.com')
        for staff in (manager, receptionist):
            self.assign_staff(staff, self.property)

        self.authenticate(manager)
        self.assertEqual(self.replace([{'code': 'wifi'}]).status_code, 200)

        self.authenticate(receptionist)
        self.assertEqual(self.client.get(features_url(self.property)).status_code, 200)
        self.assertEqual(self.client.get(reverse('tenant-feature-list')).status_code, 200)
        self.assertEqual(self.replace([{'code': 'gym'}]).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('tenant-feature-list'), {'label': 'Sauna'}, format='json').status_code, 403,
        )

        self.authenticate(resident)
        self.assertEqual(self.client.get(features_url(self.property)).status_code, 403)
        self.assertEqual(self.replace([{'code': 'gym'}]).status_code, 403)

    def test_45_46_unassigned_manager_gets_404_before_any_feature_validation(self):
        manager = self.create_manager(self.tenant)  # not assigned
        custom = self.create_tenant_feature(self.tenant)
        self.authenticate(manager)

        get = self.client.get(features_url(self.property))
        post = self.replace([{'tenant_feature': str(custom.id)}, {'code': 'no_such_feature'}])

        self.assertEqual(get.status_code, 404)
        self.assertEqual(post.status_code, 404)

    def test_47_model_clean_rejects_a_building_from_another_property(self):
        other = self.create_property(self.tenant, name='Other PG')
        other_block = self.create_building(other)
        with tenant_context(self.tenant.id):
            row = PropertyFeature(
                tenant_id=self.tenant.id, property=self.property, building=other_block,
                catalog_feature=FeatureCatalog.objects.get(code='wifi'),
            )
            with self.assertRaises(DjangoValidationError):
                row.full_clean()


class FeatureConcurrencyTests(TransactionTestCase):
    """Rule 23. Needs real commits on separate connections, so this can't be
    a transaction-wrapped TestCase."""

    def _fixture_teardown(self):
        # The default flush would also wipe migration-seeded tables
        # (feature_catalog, plans, notification templates) for the rest of
        # the run; tearDown removes exactly what this test created instead.
        pass

    def setUp(self):
        self.tenant = PropertyAPITestCase.create_tenant('Concurrency Tenant')
        self.property = PropertyAPITestCase.create_property(self.tenant)

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            Property.objects.filter(pk=self.property.pk).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        self.tenant.delete()

    def test_23_concurrent_replaces_leave_one_complete_set(self):
        sets = [
            ['wifi', 'lift', 'gym', 'cctv', 'garden'],
            ['breakfast', 'lunch', 'dinner', 'intercom', 'curtains'],
        ]
        barrier = threading.Barrier(len(sets))
        errors = []

        def worker(codes):
            try:
                barrier.wait(timeout=10)
                with tenant_context(self.tenant.id):
                    feature_services.replace_features(
                        prop=self.property, items=[{'code': code} for code in codes],
                    )
            except Exception as exc:  # noqa: BLE001 — surfaced through `errors`
                errors.append(exc)
            finally:
                connection.close()

        for _round in range(5):
            threads = [threading.Thread(target=worker, args=(codes,)) for codes in sets]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

            self.assertEqual(errors, [])
            with tenant_context(self.tenant.id):
                final = sorted(
                    PropertyFeature.objects.filter(property=self.property)
                    .values_list('catalog_feature__code', flat=True)
                )
            self.assertIn(final, [sorted(codes) for codes in sets])


class SuperAdminFeatureTests(FeatureTestCase):
    """A Super Admin has no tenant, so the tenant-owned feature endpoints have
    nothing to act on. They must say so (403) rather than crash on a NULL
    tenant_id."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.create_super_admin())

    def assertNoTenantContext(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'TENANT_CONTEXT_REQUIRED')

    def test_super_admin_cannot_use_tenant_feature_endpoints(self):
        feature = self.create_tenant_feature(self.tenant)
        detail = reverse('tenant-feature-detail', args=[feature.id])

        self.assertNoTenantContext(self.client.get(reverse('tenant-feature-list')))
        self.assertNoTenantContext(
            self.client.post(reverse('tenant-feature-list'), {'label': 'Sauna'}, format='json')
        )
        self.assertNoTenantContext(self.client.patch(detail, {'label': 'TT'}, format='json'))
        self.assertNoTenantContext(self.client.delete(detail))
        with tenant_context(self.tenant.id):
            self.assertEqual(TenantFeature.objects.get(pk=feature.pk).label, 'Table tennis')

    def test_super_admin_gets_404_for_a_pgs_features(self):
        # No tenant means no visible properties — same as every other
        # property endpoint for a Super Admin.
        self.assertEqual(self.client.get(features_url(self.property)).status_code, 404)
        self.assertEqual(self.replace([{'code': 'wifi'}]).status_code, 404)

    def test_super_admin_can_still_read_the_catalogue(self):
        self.assertEqual(self.client.get(reverse('feature-catalog-list')).status_code, 200)


class SeedMigrationRollbackTests(TransactionTestCase):
    """Reversing 0007 must not fail — or delete anything — once a property
    has selected a seeded feature (the FK is PROTECT)."""

    def _fixture_teardown(self):
        # Keep migration-seeded tables (feature_catalog, plans, ...) intact.
        pass

    def setUp(self):
        self.tenant = PropertyAPITestCase.create_tenant('Rollback Tenant')
        self.property = PropertyAPITestCase.create_property(self.tenant)
        PropertyAPITestCase.create_property_feature(self.property, code='wifi')

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            Property.objects.filter(pk=self.property.pk).delete()
        self.tenant.delete()

    def test_reversing_the_seed_migration_keeps_assigned_features(self):
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate([('properties', '0006_feature_catalog_tenant_feature_property_feature')])
        try:
            self.assertTrue(FeatureCatalog.objects.filter(code='wifi').exists())
            with tenant_context(self.tenant.id):
                self.assertEqual(PropertyFeature.objects.count(), 1)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
