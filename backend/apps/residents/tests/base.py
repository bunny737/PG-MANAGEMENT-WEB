from datetime import date

from apps.core.tenancy import tenant_context
from apps.properties.models import Bed
from apps.properties.tests.base import PropertyAPITestCase

from apps.residents.models import Admission, Allocation, Resident


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

    @classmethod
    def check_in(cls, resident, bed, **admission_kwargs):
        """Fully check a resident in outside the API: admission + occupied bed
        + Active status + initial Allocation. Returns the Allocation."""
        admission = cls.create_admission(resident, bed, **admission_kwargs)
        with tenant_context(resident.tenant_id):
            bed.status = Bed.Status.OCCUPIED
            bed.save()
            resident.status = Resident.Status.ACTIVE
            resident.save(update_fields=['status', 'updated_at'])
            return Allocation.objects.create(
                tenant_id=resident.tenant_id,
                resident=resident,
                allocated_bed=bed,
                contracted_sharing_type=admission.contracted_sharing_type,
                contracted_room_category=admission.contracted_room_category,
                contracted_rent=admission.contracted_rent,
            )
