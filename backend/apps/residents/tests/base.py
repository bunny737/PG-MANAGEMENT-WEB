from apps.core.tenancy import tenant_context
from apps.properties.tests.base import PropertyAPITestCase

from apps.residents.models import Resident


class ResidentAPITestCase(PropertyAPITestCase):
    @staticmethod
    def create_resident(prop, first_name='Ravi', phone='9000000001', **kwargs):
        with tenant_context(prop.tenant_id):
            return Resident.objects.create(
                tenant_id=prop.tenant_id, property=prop, first_name=first_name, phone=phone, **kwargs
            )
