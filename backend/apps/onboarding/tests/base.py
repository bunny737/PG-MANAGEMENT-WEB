from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense, ExpenseCategory
from apps.expenses.services import ensure_system_categories
from apps.properties.models import Building
from apps.residents.models import Resident
from apps.residents.tests.base import ResidentAPITestCase


class OnboardingAPITestCase(ResidentAPITestCase):
    def checklist(self, expected_status=200, **params):
        response = self.client.get(reverse('onboarding-checklist'), params)
        self.assertEqual(response.status_code, expected_status, getattr(response, 'data', None))
        return response.data

    @staticmethod
    def step(data, key):
        return next(step for step in data['steps'] if step['key'] == key)

    def bare_property(self, tenant, name='Bare PG'):
        """A property with no building — the fixture otherwise provisions one."""
        prop = self.create_property(tenant, name=name)
        with tenant_context(tenant.id):
            Building.objects.filter(property=prop).delete()
        return prop

    def bed_in(self, prop, room_number='101'):
        floor = self.create_floor(prop, name=f'F{room_number}', order=int(room_number))
        return self.create_bed(self.create_room(floor, room_number=room_number), bed_number=f'{room_number}-A')

    def admit(self, prop, phone='9000000001', room_number='101'):
        bed = self.bed_in(prop, room_number)
        resident = self.create_resident(prop, phone=phone, status=Resident.Status.RESERVED)
        self.check_in(resident, bed)
        return resident

    @staticmethod
    def create_expense(prop, **kwargs):
        with tenant_context(prop.tenant_id):
            ensure_system_categories(prop.tenant_id)
            category = ExpenseCategory.objects.filter(tenant_id=prop.tenant_id).first()
            return Expense.objects.create(
                tenant_id=prop.tenant_id, property=prop, category=category,
                amount=Decimal('500.00'), date=date(2026, 7, 1), payment_mode='cash', **kwargs,
            )
