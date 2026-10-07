"""Display labels, aliases and text normalisation for PG features (Module 18).

The `feature_catalog` table stores only a stable `code`; the user-facing
wording lives here so `makemessages` extracts it and each locale's .po
translates it (invariant 7). Adding a platform feature = a row in a seed
migration AND a label here — `test_pg_features` fails if the two drift.

Never import this module from a migration: migrations carry their own
literal code list (see 0007_seed_feature_catalog).
"""
import unicodedata
from functools import lru_cache

from django.utils import translation
from django.utils.translation import gettext_lazy as _

FEATURE_LABELS = {
    # rooms
    'furnished_rooms': _('Furnished rooms'),
    'cot_with_mattress': _('Cot with mattress'),
    'pillow_and_linen': _('Pillow & bed linen'),
    'cupboard_wardrobe': _('Cupboard / wardrobe'),
    'study_table_chair': _('Study table & chair'),
    'shoe_rack': _('Shoe rack'),
    'curtains': _('Curtains'),
    'attached_bathroom': _('Attached bathroom'),
    'common_bathroom': _('Common bathroom'),
    # food
    'mess_food_provided': _('Food / mess provided'),
    'breakfast': _('Breakfast'),
    'lunch': _('Lunch'),
    'dinner': _('Dinner'),
    'veg_food': _('Vegetarian food'),
    'non_veg_food': _('Non-vegetarian food'),
    'special_diet_food': _('Special / diet food'),
    'dining_hall': _('Common dining hall'),
    'ro_drinking_water': _('RO drinking water'),
    'water_cooler': _('Water cooler'),
    'tea_coffee_24x7': _('24x7 tea & coffee'),
    'common_kitchen': _('Common kitchen'),
    'refrigerator': _('Refrigerator'),
    'microwave_induction': _('Microwave / induction'),
    # housekeeping
    'room_cleaning_daily': _('Daily room cleaning'),
    'room_cleaning_weekly': _('Weekly room cleaning'),
    'common_area_cleaning': _('Common-area cleaning'),
    'bathroom_cleaning': _('Bathroom cleaning'),
    'laundry_service': _('Laundry service'),
    'washing_machine': _('Washing machine'),
    'ironing_service': _('Ironing'),
    'pest_control': _('Pest control'),
    # connectivity
    'wifi': _('Wi-Fi'),
    'tv_with_dth': _('Common TV'),
    'intercom': _('Intercom'),
    # utilities
    'power_backup': _('Power backup'),
    'hot_water_geyser': _('Hot water / geyser'),
    'water_supply_24x7': _('24x7 water supply'),
    'lift': _('Lift'),
    'solar_water_heater': _('Solar water heater'),
    # safety
    'cctv': _('CCTV surveillance'),
    'security_guard_24x7': _('Security guard'),
    'biometric_access': _('Biometric / smart access'),
    'visitor_register': _('Visitor entry management'),
    'gated_premises': _('Gated premises'),
    'fire_extinguisher': _('Fire extinguisher'),
    'smoke_detector': _('Smoke detector'),
    'first_aid_kit': _('First-aid kit'),
    'warden_on_premises': _('Warden on premises'),
    # recreation
    'gym': _('Gym'),
    'terrace_access': _('Terrace access'),
    'common_lounge': _('Common lounge'),
    'indoor_games': _('Indoor games'),
    'reading_room': _('Reading room'),
    'garden': _('Garden / open space'),
    'swimming_pool': _('Swimming pool'),
    # parking
    'two_wheeler_parking': _('Two-wheeler parking'),
    'four_wheeler_parking': _('Car parking'),
    'covered_parking': _('Covered parking'),
    'visitor_parking': _('Visitor parking'),
    'ev_charging': _('EV charging point'),
    # services
    'maintenance_on_call': _('Maintenance / repair service'),
    'parcel_handling': _('Parcel collection'),
    'front_desk_24x7': _('24x7 front desk'),
    'caretaker_on_premises': _('Caretaker on premises'),
    'doctor_on_call': _('Doctor on call'),
    'tuck_shop': _('Tuck shop / provision store'),
    'shuttle_service': _('Shuttle / drop service'),
    # accessibility
    'wheelchair_accessible': _('Wheelchair accessible'),
    'ramp_access': _('Ramp access'),
    # policies
    'no_curfew': _('No curfew'),
    'flexible_entry_timings': _('Flexible entry timings'),
    'short_term_stay': _('Short-term stay'),
}

# Extra spellings an owner might type for a platform feature. Matching is
# locale-independent on purpose: identity must not change with the request's
# Accept-Language or with a reworded translation.
FEATURE_ALIASES = {
    'wifi': ('wi-fi', 'internet', 'broadband', 'wireless internet', 'free wifi'),
    'power_backup': ('generator', 'inverter', 'ups', 'power back up'),
    'lift': ('elevator',),
    'hot_water_geyser': ('geyser', 'hot water', '24x7 hot water'),
    'cctv': ('cctv', 'cctv camera', 'cctv cameras', 'camera'),
    'security_guard_24x7': ('security', 'watchman', '24x7 security'),
    'biometric_access': ('biometric', 'smart lock', 'biometric entry'),
    'ro_drinking_water': ('ro water', 'drinking water', 'purified water', 'mineral water'),
    'refrigerator': ('fridge',),
    'microwave_induction': ('microwave', 'induction', 'oven'),
    'cot_with_mattress': ('bed', 'mattress', 'bed with mattress', 'cot'),
    'cupboard_wardrobe': ('cupboard', 'wardrobe', 'almirah'),
    'study_table_chair': ('table', 'chair', 'study table', 'table and chair'),
    'mess_food_provided': ('food', 'mess', 'meals'),
    'veg_food': ('veg', 'veg food', 'vegetarian'),
    'non_veg_food': ('non veg', 'non-veg', 'nonveg food', 'non vegetarian'),
    'laundry_service': ('laundry',),
    'ironing_service': ('ironing', 'iron'),
    'two_wheeler_parking': ('bike parking', '2 wheeler parking', 'two wheeler parking'),
    'four_wheeler_parking': ('car parking', '4 wheeler parking', 'four wheeler parking'),
    'tv_with_dth': ('tv', 'television', 'dth', 'common tv'),
    'common_lounge': ('lounge', 'common area'),
    'terrace_access': ('terrace',),
    'gym': ('fitness centre', 'fitness center'),
    'maintenance_on_call': ('maintenance', 'repair service', 'plumber', 'electrician'),
    'parcel_handling': ('parcel', 'courier'),
    'visitor_register': ('visitor management',),
    'room_cleaning_daily': ('room cleaning', 'housekeeping', 'daily cleaning'),
    'room_cleaning_weekly': ('weekly cleaning',),
    'short_term_stay': ('short stay', 'short term'),
    'flexible_entry_timings': ('flexible timings', 'flexible entry'),
}

CUSTOM_CATEGORY = 'custom'
CUSTOM_CATEGORY_LABEL = _('Your features')


def label_for(code):
    return FEATURE_LABELS.get(code) or code.replace('_', ' ').title()


def normalise(text):
    """Comparison key for feature text: NFKC, lowercase, then keep only
    Unicode letters, combining marks and numbers — so 'Wi-Fi', 'WIFI' and
    'wi fi' all collapse to 'wifi'.

    Marks are kept deliberately. Indic vowel signs are marks, so dropping
    them (which is also what `slugify(allow_unicode=True)` does) makes
    distinct Telugu/Hindi words collide. The frontend mirrors this exactly
    in `normaliseFeatureText`; tests/fixtures/feature_normalisation.json is
    asserted from both sides.
    """
    text = unicodedata.normalize('NFKC', text or '').lower()
    return ''.join(ch for ch in text if unicodedata.category(ch)[0] in 'LMN')


@lru_cache(maxsize=1)
def _alias_index():
    index = {}
    with translation.override('en'):
        for code, label in FEATURE_LABELS.items():
            index[normalise(code)] = code
            index[normalise(str(label))] = code
    for code, aliases in FEATURE_ALIASES.items():
        for alias in aliases:
            index.setdefault(normalise(alias), code)
    return index


def match_catalog_code(text):
    """The platform feature code `text` refers to (by code, English label or
    a listed alias), or None. Never consults translations."""
    return _alias_index().get(normalise(text))
