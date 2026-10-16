"""Module 20 — expenses: CRUD, soft delete, summary, categories, attachments,
permissions, property scope, idempotency and tenant isolation."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.billing.tests.base import BillingAPITestCase
from apps.core.periods import local_today
from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense, ExpenseCategory
from apps.expenses.services import ensure_system_categories

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
PDF = b'%PDF-1.4\n' + b'0' * 32


class ExpenseAPITestCase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant, name='A')
        self.other_prop = self.create_property(self.tenant, name='B')
        self.authenticate(self.owner)
        categories = self.client.get(reverse('expense-category-list')).data
        self.categories = {row['code']: row['id'] for row in categories}

    def create(self, amount='1200.00', when=None, prop=None, category='electricity', **extra):
        body = {
            'property': str((prop or self.prop).id), 'category': self.categories[category],
            'amount': amount, 'date': (when or date(2026, 9, 5)).isoformat(),
            'payment_mode': 'upi', 'note': 'Sept bill', **extra,
        }
        return self.client.post(reverse('expense-list'), body, format='multipart' if 'attachment' in extra else None)


class ExpenseCrudTests(ExpenseAPITestCase):
    def test_categories_are_seeded_once_with_stable_ids(self):
        again = {row['code']: row['id'] for row in self.client.get(reverse('expense-category-list')).data}
        self.assertEqual(again, self.categories)
        self.assertIn('other', self.categories)
        with tenant_context(self.tenant.id):
            ensure_system_categories(self.tenant.id)
            self.assertEqual(ExpenseCategory.objects.filter(is_system=True).count(), len(self.categories))

    def test_create_list_and_audit(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['category_name'], 'Electricity')
        self.assertEqual(response.data['created_by'], self.owner.id)
        self.assertFalse(response.data['has_attachment'])
        self.assertEqual(len(self.client.get(reverse('expense-list')).data), 1)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='expense.created').exists())

    def test_validation(self):
        self.assertEqual(self.create(amount='0').status_code, 400)
        response = self.create(when=local_today() + timedelta(days=1))
        self.assertEqual(response.data['date'][0].code, 'future_date')
        response = self.client.post(reverse('expense-list'), {
            'category': self.categories['water'], 'amount': '10', 'date': '2026-09-01', 'payment_mode': 'cash',
        })
        self.assertIn('property', response.data)  # property is required

    def test_filters(self):
        self.create(when=date(2026, 9, 5))
        self.create(when=date(2026, 8, 5), category='water', note='August water')
        self.create(prop=self.other_prop)
        url = reverse('expense-list')
        self.assertEqual(len(self.client.get(url, {'month': '2026-09'}).data), 2)
        self.assertEqual(len(self.client.get(url, {'property': str(self.other_prop.id)}).data), 1)
        self.assertEqual(len(self.client.get(url, {'category': self.categories['water']}).data), 1)
        self.assertEqual(len(self.client.get(url, {'search': 'august'}).data), 1)

    def test_soft_delete_is_excluded_from_list_summary_and_export(self):
        keep = self.create(amount='100.00').data['id']
        gone = self.create(amount='900.00').data['id']
        self.assertEqual(self.client.delete(reverse('expense-detail', args=[gone])).status_code, 204)
        self.assertEqual([row['id'] for row in self.client.get(reverse('expense-list')).data], [keep])
        summary = self.client.get(reverse('expense-summary'), {'month': '2026-09'}).data
        self.assertEqual((summary['total'], summary['count']), ('100.00', 1))
        export = self.client.get(reverse('export-expenses'), {'month': '2026-09'})
        self.assertNotIn(b'900.00', export.content)
        with tenant_context(self.tenant.id):
            row = Expense.objects.get(pk=gone)
            self.assertIsNotNone(row.deleted_at)
            self.assertEqual(row.deleted_by_id, self.owner.id)

    def test_summary_by_category(self):
        self.create(amount='100.00')
        self.create(amount='50.00')
        self.create(amount='300.00', category='water')
        data = self.client.get(reverse('expense-summary'), {'month': '2026-09'}).data
        self.assertEqual(data['total'], '450.00')
        self.assertEqual([(r['code'], r['total'], r['count']) for r in data['by_category']],
                         [('water', '300.00', 1), ('electricity', '150.00', 2)])

    def test_update_moves_month_and_is_audited(self):
        expense_id = self.create().data['id']
        response = self.client.patch(reverse('expense-detail', args=[expense_id]), {'date': '2026-08-30'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.client.get(reverse('expense-list'), {'month': '2026-08'}).data), 1)
        with tenant_context(self.tenant.id):
            log = AuditLog.objects.get(action='expense.updated')
        self.assertEqual((log.before['date'], log.after['date']), ('2026-09-05', '2026-08-30'))

    def test_full_put_is_not_allowed(self):
        expense_id = self.create().data['id']
        self.assertEqual(self.client.put(reverse('expense-detail', args=[expense_id]), {}).status_code, 405)

    def test_idempotent_create(self):
        first = self.client.post(reverse('expense-list'), {
            'property': str(self.prop.id), 'category': self.categories['gas'], 'amount': '800.00',
            'date': '2026-09-02', 'payment_mode': 'cash',
        }, HTTP_IDEMPOTENCY_KEY='exp-1')
        second = self.client.post(reverse('expense-list'), {
            'property': str(self.prop.id), 'category': self.categories['gas'], 'amount': '800.00',
            'date': '2026-09-02', 'payment_mode': 'cash',
        }, HTTP_IDEMPOTENCY_KEY='exp-1')
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.data['id'], second.data['id'])
        clash = self.client.post(reverse('expense-list'), {
            'property': str(self.prop.id), 'category': self.categories['gas'], 'amount': '999.00',
            'date': '2026-09-02', 'payment_mode': 'cash',
        }, HTTP_IDEMPOTENCY_KEY='exp-1')
        self.assertEqual(clash.status_code, 409)


@override_settings(EXPENSE_ATTACHMENT_MAX_BYTES=1024)
class ExpenseAttachmentTests(ExpenseAPITestCase):
    def test_upload_on_create_get_url_replace_and_remove(self):
        response = self.create(attachment=SimpleUploadedFile('bill.png', PNG, content_type='image/png'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['has_attachment'])
        self.assertEqual(response.data['attachment_content_type'], 'image/png')
        url = reverse('expense-attachment', args=[response.data['id']])
        link = self.client.get(url).data
        self.assertIn('/media/expenses/', link['url'])
        self.assertNotIn('bill', link['url'])  # stored under a random name
        replaced = self.client.put(url, {'attachment': SimpleUploadedFile('b.pdf', PDF)}, format='multipart')
        self.assertEqual(replaced.data['attachment_content_type'], 'application/pdf')
        removed = self.client.delete(url)
        self.assertFalse(removed.data['has_attachment'])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_type_is_sniffed_not_trusted(self):
        fake = SimpleUploadedFile('bill.png', b'MZ\x90\x00not-an-image', content_type='image/png')
        response = self.create(attachment=fake)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['attachment'][0].code, 'attachment_type_not_allowed')

    def test_size_limit(self):
        big = SimpleUploadedFile('big.pdf', b'%PDF-' + b'0' * 2048)
        self.assertEqual(self.create(attachment=big).data['attachment'][0].code, 'attachment_too_large')


class ExpenseCategoryTests(ExpenseAPITestCase):
    def test_custom_category_lifecycle(self):
        created = self.client.post(reverse('expense-category-list'), {'name': 'Pest control'})
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(
            self.client.post(reverse('expense-category-list'), {'name': 'pest CONTROL'}).data['name'][0].code,
            'duplicate_category',
        )
        self.categories['pest'] = created.data['id']
        self.create(category='pest')
        detail = reverse('expense-category-detail', args=[created.data['id']])
        self.assertEqual(self.client.delete(detail).data['code'], 'CATEGORY_IN_USE')
        self.assertEqual(self.client.patch(detail, {'is_archived': True}).status_code, 200)
        listed = {row['id'] for row in self.client.get(reverse('expense-category-list')).data}
        self.assertNotIn(created.data['id'], listed)
        self.assertEqual(self.create(category='pest').data['category'][0].code, 'category_archived')

    def test_system_categories_are_immutable(self):
        detail = reverse('expense-category-detail', args=[self.categories['water']])
        self.assertEqual(self.client.patch(detail, {'name': 'H2O'}).data['code'], 'SYSTEM_CATEGORY')
        self.assertEqual(self.client.delete(detail).status_code, 409)

    def test_unused_custom_category_can_be_deleted(self):
        created = self.client.post(reverse('expense-category-list'), {'name': 'Misc'}).data
        self.assertEqual(
            self.client.delete(reverse('expense-category-detail', args=[created['id']])).status_code, 204,
        )


class ExpensePermissionTests(ExpenseAPITestCase):
    def test_receptionist_has_no_access(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.prop)
        self.authenticate(receptionist)
        self.assertEqual(self.client.get(reverse('expense-list')).status_code, 403)

    def test_view_level_reads_but_cannot_write(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.customize(manager, expenses='view')
        self.authenticate(manager)
        self.assertEqual(self.client.get(reverse('expense-list')).status_code, 200)
        self.assertEqual(self.create().status_code, 403)

    def test_manager_only_sees_and_writes_assigned_properties(self):
        self.create(prop=self.other_prop)
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.authenticate(manager)
        self.assertEqual(self.client.get(reverse('expense-list')).data, [])
        response = self.create(prop=self.other_prop)
        self.assertEqual(response.data['property'][0].code, 'property_not_assigned')
        self.assertEqual(
            self.client.get(reverse('expense-summary'), {'property': str(self.other_prop.id)}).status_code, 404,
        )


class ExpenseRowLevelSecurityTests(TestCase):
    def setUp(self):
        helper = BillingAPITestCase
        self.tenant_a = helper.create_tenant('A')
        self.tenant_b = helper.create_tenant('B')
        prop_a = helper.create_property(self.tenant_a)
        with tenant_context(self.tenant_a.id):
            ensure_system_categories(self.tenant_a.id)
            category = ExpenseCategory.objects.get(code='water')
            self.expense = Expense.objects.create(
                tenant_id=self.tenant_a.id, property=prop_a, category=category,
                amount=Decimal('10.00'), date=date(2026, 9, 1), payment_mode='cash',
            )
        self.category = category

    def test_other_tenant_sees_nothing(self):
        with tenant_context(self.tenant_b.id):
            self.assertEqual(Expense.objects.count(), 0)
            self.assertEqual(ExpenseCategory.objects.count(), 0)
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Expense.objects.count(), 1)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Expense.objects.create(
                        tenant_id=self.tenant_b.id, property=self.expense.property, category=self.category,
                        amount=Decimal('1.00'), date=date(2026, 9, 1), payment_mode='cash',
                    )
