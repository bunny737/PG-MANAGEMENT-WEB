from datetime import date

from apps.core.tenancy import tenant_context
from apps.properties.tests.base import PropertyAPITestCase

from apps.residents.models import Admission, Resident


class ResidentAPITestCase(PropertyAPITestCase):
    @staticmethod
    def create_resident(prop, first_name='Ravi', phone='9000000001', **kwargs):
        with tenant_context(prop.tenant_id):
            return Resident.objects.create(
                tenant_id=prop.tenant_id, property=prop, first_name=first_name, phone=phone, **kwargs
            )

    @staticmethod
    def create_admission(resident, bed, **kwargs):
        kwargs.setdefault('joining_date', date.today())
        kwargs.setdefault('billing_mode', Admission.BillingMode.MONTHLY)
        kwargs.setdefault('food_preference', Admission.FoodPreference.WITH_FOOD)
        kwargs.setdefault('contracted_sharing_type', bed.room.sharing_type)
        kwargs.setdefault('contracted_room_category', bed.room.category)
        kwargs.setdefault('contracted_rent', bed.rack_rate(with_food=True))
        with tenant_context(resident.tenant_id):
            return Admission.objects.create(
                tenant_id=resident.tenant_id, resident=resident, bed=bed, **kwargs
            )
