from datetime import date

from apps.core.tenancy import tenant_context
from apps.properties.models import Bed
from apps.properties.tests.base import PropertyAPITestCase

from apps.residents.models import AbscondedRecord, Admission, Allocation, BlacklistEntry, Resident, Vacate


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

    @staticmethod
    def create_vacate(resident, notice_given_date=None, expected_vacate_date=None, **kwargs):
        if notice_given_date is None:
            notice_given_date = date(2026, 7, 1)
        if expected_vacate_date is None:
            expected_vacate_date = date(2026, 8, 1)
        with tenant_context(resident.tenant_id):
            return Vacate.objects.create(
                tenant_id=resident.tenant_id, resident=resident,
                notice_given_date=notice_given_date, expected_vacate_date=expected_vacate_date, **kwargs
            )

    @staticmethod
    def create_absconded_record(resident, absconded_date=None, **kwargs):
        if absconded_date is None:
            absconded_date = date(2026, 7, 1)
        kwargs.setdefault('advance_applied_to_dues', 0)
        kwargs.setdefault('remaining_dues', 0)
        with tenant_context(resident.tenant_id):
            return AbscondedRecord.objects.create(
                tenant_id=resident.tenant_id, resident=resident, absconded_date=absconded_date, **kwargs
            )

    @staticmethod
    def create_blacklist_entry(resident, **kwargs):
        with tenant_context(resident.tenant_id):
            return BlacklistEntry.objects.create(
                tenant_id=resident.tenant_id, resident=resident,
                phone=resident.phone, aadhaar_number=resident.aadhaar_number, **kwargs
            )
