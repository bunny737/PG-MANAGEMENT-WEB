from apps.core.tenancy import tenant_context
from apps.residents.tests.base import ResidentAPITestCase

from apps.operations.models import Complaint


class OperationsAPITestCase(ResidentAPITestCase):
    @staticmethod
    def create_complaint(resident, category=Complaint.Category.ELECTRICAL,
                         description='The fan in the room is not working.', **kwargs):
        with tenant_context(resident.tenant_id):
            return Complaint.objects.create(
                tenant_id=resident.tenant_id, resident=resident, category=category,
                description=description, **kwargs
            )
