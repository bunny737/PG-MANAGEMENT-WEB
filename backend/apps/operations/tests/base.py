from datetime import datetime, timezone as dt_timezone

from apps.core.tenancy import tenant_context
from apps.residents.tests.base import ResidentAPITestCase

from apps.operations.models import Complaint, Visitor


class OperationsAPITestCase(ResidentAPITestCase):
    @staticmethod
    def create_complaint(resident, category=Complaint.Category.ELECTRICAL,
                         description='The fan in the room is not working.', **kwargs):
        with tenant_context(resident.tenant_id):
            return Complaint.objects.create(
                tenant_id=resident.tenant_id, resident=resident, category=category,
                description=description, **kwargs
            )

    @staticmethod
    def create_visitor(resident, visitor_name='Ramesh Kumar', mobile_number='9000000099',
                       purpose='Family visit', entry_time=None, **kwargs):
        if entry_time is None:
            entry_time = datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc)
        with tenant_context(resident.tenant_id):
            return Visitor.objects.create(
                tenant_id=resident.tenant_id, resident=resident, visitor_name=visitor_name,
                mobile_number=mobile_number, purpose=purpose, entry_time=entry_time, **kwargs
            )
