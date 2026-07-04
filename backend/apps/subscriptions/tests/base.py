from apps.residents.tests.base import ResidentAPITestCase

from apps.subscriptions.models import Plan, Subscription


class SubscriptionAPITestCase(ResidentAPITestCase):
    @staticmethod
    def create_plan(name='Starter', max_properties=1, max_residents_per_property=10,
                    price_per_month='199.00', **kwargs):
        return Plan.objects.create(
            name=name, max_properties=max_properties,
            max_residents_per_property=max_residents_per_property,
            price_per_month=price_per_month, **kwargs
        )

    @staticmethod
    def create_subscription(tenant, plan=None, **kwargs):
        return Subscription.objects.create(tenant=tenant, plan=plan, **kwargs)
