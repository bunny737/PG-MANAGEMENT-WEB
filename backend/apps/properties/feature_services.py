"""PG features (Module 18): the single write path for TenantFeature and
PropertyFeature, plus the read-side merge of property and building rows.

Everything that compares features keys off `identity()`:
    ('catalog', <code>)  or  ('custom', <tenant feature uuid as str>)
"""
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.audit import log as audit_log

from .feature_catalog import CUSTOM_CATEGORY, match_catalog_code, normalise
from .models import Building, FeatureCatalog, Property, PropertyFeature, Room, TenantFeature

MAX_FEATURES_PER_SCOPE = 200
MAX_LABEL_LENGTH = TenantFeature._meta.get_field('label').max_length

_CATEGORY_ORDER = {value: index for index, value in enumerate(FeatureCatalog.Category.values)}


def _error(message, code, **extra):
    return ValidationError({'detail': message, **extra}, code=code)


def identity(row):
    if row.catalog_feature_id:
        return ('catalog', row.catalog_feature.code)
    return ('custom', str(row.tenant_feature_id))


def _rows(prop):
    return list(
        PropertyFeature.objects.filter(property=prop).select_related('catalog_feature', 'tenant_feature')
    )


def _sort_key(row):
    if row.catalog_feature_id:
        feature = row.catalog_feature
        return (_CATEGORY_ORDER.get(feature.category, len(_CATEGORY_ORDER)), feature.display_order, feature.code)
    return (len(_CATEGORY_ORDER) + 1, 0, row.tenant_feature.label.lower())


def derived_facts(prop, building=None):
    """Facts already modelled on Room, surfaced read-only next to the
    features so sharing type / AC never get re-entered as features."""
    rooms = Room.objects.filter(floor__building__property_id=prop.id)
    if building is not None:
        rooms = rooms.filter(floor__building_id=building.id)
    return {
        'sharing_types': sorted(set(rooms.values_list('sharing_type', flat=True))),
        'room_categories': sorted(set(rooms.values_list('category', flat=True))),
    }


def get_building(prop, building_id):
    if not building_id:
        return None
    building = Building.objects.filter(pk=building_id, property_id=prop.id).first()
    if building is None:
        raise _error(_('This building does not belong to the property.'), 'building_not_in_property')
    return building


def feature_state(prop, building=None):
    """(rows, excluded_rows, derived) for the API.

    Without a building: every row of the PG, each at its own scope.
    With a building: the effective set — property rows merged with that
    building's rows by identity, the building row winning; a building row
    with is_available=False removes the inherited feature and is reported
    in `excluded` instead.
    """
    rows = _rows(prop)
    if building is None:
        items = [row for row in rows if row.is_available]
        excluded = [row for row in rows if not row.is_available]
    else:
        merged = {identity(row): row for row in rows if row.building_id is None}
        excluded = []
        for row in rows:
            if row.building_id != building.id:
                continue
            if row.is_available:
                merged[identity(row)] = row
            else:
                merged.pop(identity(row), None)
                excluded.append(row)
        items = list(merged.values())
    return sorted(items, key=_sort_key), sorted(excluded, key=_sort_key), derived_facts(prop, building)


def _audit_snapshot(rows):
    return sorted(
        (
            {
                'type': identity(row)[0], 'key': identity(row)[1],
                'is_paid': row.is_paid, 'is_available': row.is_available,
            }
            for row in rows
        ),
        key=lambda item: (item['type'], item['key']),
    )


def _resolve(prop, entries):
    """[{code|tenant_feature, is_paid?}] -> {identity: (catalog, tenant_feature, is_paid)}."""
    codes = [entry['code'] for entry in entries if entry.get('code')]
    custom_ids = [entry['tenant_feature'] for entry in entries if entry.get('tenant_feature')]
    catalog = {feature.code: feature for feature in FeatureCatalog.objects.filter(code__in=codes)}
    custom = {
        feature.id: feature
        for feature in TenantFeature.objects.filter(tenant_id=prop.tenant_id, id__in=custom_ids)
    }
    resolved = {}
    for entry in entries:
        code, custom_id = entry.get('code'), entry.get('tenant_feature')
        if code and custom_id:
            raise _error(_('Give either a feature code or a custom feature, not both.'), 'feature_source_ambiguous')
        if not code and not custom_id:
            raise _error(_('Each feature needs a code or a custom feature.'), 'feature_source_required')
        feature = catalog.get(code) if code else custom.get(custom_id)
        if feature is None:
            raise _error(_('Unknown feature.'), 'unknown_feature')
        key = ('catalog', feature.code) if code else ('custom', str(feature.id))
        if key in resolved:
            raise _error(_('The same feature is listed more than once.'), 'duplicate_feature')
        resolved[key] = (feature if code else None, None if code else feature, bool(entry.get('is_paid', False)))
    return resolved


@transaction.atomic
def replace_features(*, prop, building_id=None, items=(), excluded=(), actor=None, request=None):
    """Replace the whole feature set at exactly one scope: the property
    (building_id None) or one of its buildings. Other scopes are untouched.
    """
    # Serialises every feature edit on this PG. atomic() alone would let two
    # concurrent replaces interleave their deletes/creates into a hybrid set.
    Property.objects.select_for_update().get(pk=prop.pk)
    building = get_building(prop, building_id)

    if excluded and building is None:
        raise _error(
            _('A feature can only be marked unavailable for a specific building.'),
            'suppression_requires_building',
        )
    if len(items) + len(excluded) > MAX_FEATURES_PER_SCOPE:
        raise _error(_('Too many features.'), 'too_many_features')

    target = _resolve(prop, [*items, *excluded])
    offered_keys = set(list(target)[:len(items)])

    all_rows = _rows(prop)
    scope_rows = {identity(row): row for row in all_rows if row.building_id == (building.id if building else None)}
    property_keys = {identity(row) for row in all_rows if row.building_id is None}
    before = _audit_snapshot(scope_rows.values())

    for key, (catalog_feature, tenant_feature, _is_paid) in target.items():
        feature = catalog_feature or tenant_feature
        if key in offered_keys:
            existing = scope_rows.get(key)
            # A retired feature may stay where it already is, but can't be newly offered.
            if not feature.is_active and not (existing and existing.is_available):
                raise _error(_('This feature is no longer available.'), 'feature_not_active')
        elif key not in property_keys:
            raise _error(
                _('Only a feature offered by the whole PG can be marked unavailable for a building.'),
                'nothing_to_suppress',
            )

    for key, row in scope_rows.items():
        if key not in target:
            row.delete()
    for key, (catalog_feature, tenant_feature, is_paid) in target.items():
        is_available = key in offered_keys
        is_paid = is_paid and is_available
        row = scope_rows.get(key)
        if row is None:
            scope_rows[key] = PropertyFeature.objects.create(
                tenant_id=prop.tenant_id, property=prop, building=building,
                catalog_feature=catalog_feature, tenant_feature=tenant_feature,
                is_available=is_available, is_paid=is_paid,
            )
        elif (row.is_available, row.is_paid) != (is_available, is_paid):
            row.is_available, row.is_paid = is_available, is_paid
            row.save(update_fields=['is_available', 'is_paid', 'updated_at'])

    if building is None:
        # A building can't keep suppressing something the PG no longer offers.
        for row in all_rows:
            if row.building_id and not row.is_available and identity(row) not in offered_keys:
                row.delete()

    after = _audit_snapshot(row for key, row in scope_rows.items() if key in target)
    if before != after:
        scope = {'building': str(building.id) if building else None}
        audit_log.record(
            action='property_features.updated', actor=actor, tenant_id=prop.tenant_id, obj=prop,
            before={**scope, 'items': before}, after={**scope, 'items': after}, request=request,
        )
    return building


def _clean_label(label):
    """Validated (label, slug) for a custom feature, or raises."""
    label = ' '.join((label or '').split())
    slug = normalise(label)
    if not slug:
        raise _error(_('Enter a feature name.'), 'feature_label_required')
    if len(label) > MAX_LABEL_LENGTH:
        raise _error(_('Feature name is too long.'), 'feature_label_too_long')
    catalog_code = match_catalog_code(label)
    if catalog_code:
        raise _error(
            _('This feature is already in the standard list.'), 'feature_in_global_catalog',
            catalog_code=catalog_code,
        )
    return label, slug


def create_tenant_feature(*, tenant_id, label, actor=None, request=None):
    """(feature, created). Idempotent on the normalised label so type-to-add
    survives a double-click or a stale client list."""
    label, slug = _clean_label(label)
    try:
        with transaction.atomic():
            feature, created = TenantFeature.objects.get_or_create(
                tenant_id=tenant_id, slug=slug, defaults={'label': label},
            )
    except IntegrityError:
        feature, created = TenantFeature.objects.get(tenant_id=tenant_id, slug=slug), False
    if created:
        audit_log.record(
            action='tenant_feature.created', actor=actor, tenant_id=tenant_id, obj=feature,
            after={'label': feature.label}, request=request,
        )
    return feature, created


def update_tenant_feature(feature, *, label=None, is_active=None, actor=None, request=None):
    before = {'label': feature.label, 'is_active': feature.is_active}
    if label is not None:
        label, slug = _clean_label(label)
        duplicate = TenantFeature.objects.filter(tenant_id=feature.tenant_id, slug=slug).exclude(pk=feature.pk)
        if duplicate.exists():
            raise _error(_('You already have a feature with this name.'), 'feature_already_exists')
        feature.label, feature.slug = label, slug
    if is_active is not None:
        feature.is_active = is_active
    try:
        with transaction.atomic():
            feature.save()
    except IntegrityError:
        raise _error(_('You already have a feature with this name.'), 'feature_already_exists')
    after = {'label': feature.label, 'is_active': feature.is_active}
    if before != after:
        # The label changes everywhere this feature is already assigned.
        audit_log.record(
            action='tenant_feature.updated', actor=actor, tenant_id=feature.tenant_id, obj=feature,
            before=before, after=after, request=request,
        )
    return feature


def delete_tenant_feature(feature, *, actor=None, request=None):
    if feature.property_features.exists():
        raise _error(
            _('Remove this feature from your properties before deleting it.'), 'feature_in_use',
        )
    audit_log.record(
        action='tenant_feature.deleted', actor=actor, tenant_id=feature.tenant_id, obj=feature,
        before={'label': feature.label}, request=request,
    )
    feature.delete()


def category_of(row):
    return row.catalog_feature.category if row.catalog_feature_id else CUSTOM_CATEGORY
