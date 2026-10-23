# Seeds the platform feature catalogue (Module 18). Codes only — the
# translatable labels live in apps.properties.feature_catalog.FEATURE_LABELS
# (never imported here; a test asserts the two lists stay in sync).
#
# No tenant_context() wrapper: feature_catalog is a global table with no RLS.
from django.db import migrations

# category -> [(code, is_popular), ...] in display order.
FEATURES = {
    'rooms': [
        ('furnished_rooms', True), ('cot_with_mattress', False), ('pillow_and_linen', False),
        ('cupboard_wardrobe', False), ('study_table_chair', False), ('shoe_rack', False),
        ('curtains', False), ('attached_bathroom', True), ('common_bathroom', False),
    ],
    'food': [
        ('mess_food_provided', True), ('breakfast', False), ('lunch', False), ('dinner', False),
        ('veg_food', False), ('non_veg_food', False), ('special_diet_food', False),
        ('dining_hall', False), ('ro_drinking_water', True), ('water_cooler', False),
        ('tea_coffee_24x7', False), ('common_kitchen', False), ('refrigerator', True),
        ('microwave_induction', False),
    ],
    'housekeeping': [
        ('room_cleaning_daily', True), ('room_cleaning_weekly', False), ('common_area_cleaning', False),
        ('bathroom_cleaning', False), ('laundry_service', True), ('washing_machine', True),
        ('ironing_service', False), ('pest_control', False),
    ],
    'connectivity': [('wifi', True), ('tv_with_dth', False), ('intercom', False)],
    'utilities': [
        ('power_backup', True), ('hot_water_geyser', True), ('water_supply_24x7', False),
        ('lift', True), ('solar_water_heater', False),
    ],
    'safety': [
        ('cctv', True), ('security_guard_24x7', True), ('biometric_access', False),
        ('visitor_register', False), ('gated_premises', False), ('fire_extinguisher', False),
        ('smoke_detector', False), ('first_aid_kit', False), ('warden_on_premises', False),
    ],
    'recreation': [
        ('gym', False), ('terrace_access', False), ('common_lounge', False), ('indoor_games', False),
        ('reading_room', False), ('garden', False), ('swimming_pool', False),
    ],
    'parking': [
        ('two_wheeler_parking', True), ('four_wheeler_parking', False), ('covered_parking', False),
        ('visitor_parking', False), ('ev_charging', False),
    ],
    'services': [
        ('maintenance_on_call', False), ('parcel_handling', False), ('front_desk_24x7', False),
        ('caretaker_on_premises', False), ('doctor_on_call', False), ('tuck_shop', False),
        ('shuttle_service', False),
    ],
    'accessibility': [('wheelchair_accessible', False), ('ramp_access', False)],
    'policies': [('no_curfew', False), ('flexible_entry_timings', False), ('short_term_stay', False)],
}


def seed(apps, schema_editor):
    FeatureCatalog = apps.get_model('properties', 'FeatureCatalog')
    for category, features in FEATURES.items():
        for index, (code, is_popular) in enumerate(features, start=1):
            FeatureCatalog.objects.get_or_create(
                code=code,
                defaults={'category': category, 'display_order': index * 10, 'is_popular': is_popular},
            )


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0006_feature_catalog_tenant_feature_property_feature'),
    ]

    operations = [
        # Reversing is a deliberate no-op: property_features.catalog_feature is
        # PROTECT, so deleting the seeded rows would fail (and, if forced, wipe
        # tenants' selections) once any property has picked a feature. Reversing
        # 0006 afterwards drops the table anyway.
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
