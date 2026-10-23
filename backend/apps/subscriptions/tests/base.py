from apps.residents.tests.base import ResidentAPITestCase

from apps.subscriptions.models import Plan, PlanBedTier, Subscription


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
    def create_bed_plan(name='Per-Bed', bed_tiers=(), **kwargs):
        """A PER_BED_MONTHLY plan with a bed-tier ladder. `bed_tiers` is an
        iterable of `(up_to_beds, rate_per_bed)` pairs, e.g.
        `[(50, '0.00'), (300, '2.00'), (None, '1.50')]` for a 50-bed free
        allowance, ₹2/bed up to 300, ₹1.50/bed above."""
        kwargs.setdefault('pricing_type', Plan.PricingType.PER_BED_MONTHLY)
        kwargs.setdefault('price_per_month', None)
        kwargs.setdefault('max_properties', None)
        kwargs.setdefault('max_residents_per_property', None)
        plan = Plan.objects.create(name=name, **kwargs)
        for up_to_beds, rate_per_bed in bed_tiers:
            PlanBedTier.objects.create(plan=plan, up_to_beds=up_to_beds, rate_per_bed=rate_per_bed)
        return plan

    @staticmethod
    def create_subscription(tenant, plan=None, **kwargs):
        return Subscription.objects.create(tenant=tenant, plan=plan, **kwargs)
