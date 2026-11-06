"""The Getting started checklist (Module 23). The contract (step order,
`permitted` / `blocked_by`, the counted set, status precedence, target-property
ranking) is specified in docs/modules/23-getting-started.md — keep the two in sync.

Every figure is an existence check with an explicit tenant filter on top of
property visibility and RLS, and the whole request is a constant number of
queries however many properties the caller has."""
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When

from apps.core.roles import permissions_for_user
from apps.expenses.models import Expense
from apps.properties.models import Bed, Building, Floor, Property
from apps.properties.services import scoped_property_ids, visible_property_ids
from apps.residents.models import Admission

IN_PROGRESS = 'in_progress'
COMPLETED = 'completed'
NO_ACTIONS = 'no_actions'

ADD_PROPERTY = 'add_property'
RECORD_EXPENSE = 'record_expense'

# Required steps after add_property, in order, with the annotation that marks
# each done on a property. Each depends on the one before it.
HIERARCHY_STEPS = (
    ('add_building', 'has_building'),
    ('add_floor', 'has_floor'),
    ('add_room', 'has_bed'),  # rooms and beds are one step: a room counts once it has a bed
    ('admit_resident', 'has_admission'),
)
REQUIRED_STEPS = (ADD_PROPERTY,) + tuple(key for key, _ in HIERARCHY_STEPS)

STEP_PERMISSIONS = {
    ADD_PROPERTY: 'manage_properties',
    'add_building': 'manage_rooms_beds',
    'add_floor': 'manage_rooms_beds',
    'add_room': 'manage_rooms_beds',
    'admit_resident': 'manage_admissions',
    RECORD_EXPENSE: 'manage_expenses',
}

VIDEO_TOPICS = {key: key for key in REQUIRED_STEPS} | {RECORD_EXPENSE: 'expenses'}

# Target-property ranks: the caller can act now < blocked on someone else < done.
RANK_ACTIONABLE, RANK_BLOCKED, RANK_COMPLETE = 0, 1, 2


def _annotated_properties(user):
    tenant_id = user.tenant_id
    prop = OuterRef('pk')
    return Property.objects.filter(tenant_id=tenant_id, id__in=visible_property_ids(user)).annotate(
        has_building=Exists(Building.objects.filter(tenant_id=tenant_id, property=prop)),
        has_floor=Exists(Floor.objects.filter(tenant_id=tenant_id, building__property=prop)),
        has_bed=Exists(Bed.objects.filter(tenant_id=tenant_id, room__floor__building__property=prop)),
        has_admission=Exists(Admission.objects.filter(tenant_id=tenant_id, resident__property=prop)),
        has_expense=Exists(Expense.objects.filter(tenant_id=tenant_id, property=prop, deleted_at__isnull=True)),
    )


def _rank(permitted):
    """Case expression ranking a property for this caller (see RANK_*)."""
    actionable, complete = [], []
    for index, (key, flag) in enumerate(HIERARCHY_STEPS):
        if key not in permitted:
            continue
        # This step is the first not-done one: every earlier step done, this one not.
        first_not_done = Q(**{flag: False})
        for _, earlier in HIERARCHY_STEPS[:index]:
            first_not_done &= Q(**{earlier: True})
        actionable.append(first_not_done)
        complete.append(Q(**{flag: True}))
    if not complete:
        # Nothing on a property is the caller's to do; every property ranks alike.
        return Value(RANK_COMPLETE, output_field=IntegerField())
    any_actionable, all_complete = actionable[0], complete[0]
    for condition in actionable[1:]:
        any_actionable |= condition
    for condition in complete[1:]:
        all_complete &= condition
    return Case(
        When(any_actionable, then=Value(RANK_ACTIONABLE)),
        When(all_complete, then=Value(RANK_COMPLETE)),
        default=Value(RANK_BLOCKED),
        output_field=IntegerField(),
    )


def _target_property(user, property_id, permitted):
    properties = _annotated_properties(user)
    if property_id not in (None, ''):
        # 404 for a property the caller can't see — never a silent empty checklist.
        return properties.filter(id__in=scoped_property_ids(user, property_id)).first()
    return properties.annotate(rank=_rank(permitted)).order_by('rank', 'created_at', 'id').first()


def _oldest_id(queryset):
    return queryset.order_by('created_at', 'id').values_list('id', flat=True).first()


def _step(key, *, required, done, permitted, blocked_by, params):
    return {
        'key': key,
        'required': required,
        'done': done,
        'permitted': permitted,
        'blocked_by': blocked_by,
        'params': params,
        'video_topic': VIDEO_TOPICS[key],
    }


def build_checklist(user, property_id=None):
    codes = set(permissions_for_user(user))
    permitted = {key for key, code in STEP_PERMISSIONS.items() if code in codes}
    target = _target_property(user, property_id, permitted)

    done = {ADD_PROPERTY: target is not None}
    for key, flag in HIERARCHY_STEPS:
        done[key] = bool(target is not None and getattr(target, flag))

    params = {key: {} for key in STEP_PERMISSIONS}
    if target is not None:
        for key in STEP_PERMISSIONS:
            if key != ADD_PROPERTY:
                params[key] = {'property_id': str(target.id)}
        if target.has_building:
            building_id = _oldest_id(Building.objects.filter(tenant_id=user.tenant_id, property=target))
            params['add_floor']['building_id'] = str(building_id)
        if target.has_floor:
            floor_id = _oldest_id(Floor.objects.filter(tenant_id=user.tenant_id, building__property=target))
            params['add_room']['floor_id'] = str(floor_id)

    steps = []
    first_not_done = None
    for key in REQUIRED_STEPS:
        steps.append(_step(
            key, required=True, done=done[key], permitted=key in permitted,
            blocked_by=first_not_done, params=params[key],
        ))
        if first_not_done is None and not done[key]:
            first_not_done = key
    steps.append(_step(
        RECORD_EXPENSE, required=False,
        done=bool(target is not None and target.has_expense),
        permitted=RECORD_EXPENSE in permitted,
        # Recording an expense only needs a property, never the rest of the hierarchy.
        blocked_by=None if target is not None else ADD_PROPERTY,
        params=params[RECORD_EXPENSE],
    ))

    counted = [step for step in steps if step['required'] and step['permitted']]
    next_step = next((s['key'] for s in counted if not s['done'] and s['blocked_by'] is None), None)
    if not counted:
        status = NO_ACTIONS
    elif all(step['done'] for step in counted):
        status = COMPLETED
    elif next_step is not None:
        status = IN_PROGRESS
    else:
        status = NO_ACTIONS  # the first not-done step belongs to someone else

    return {
        'status': status,
        'dismissed': user.onboarding_dismissed_at is not None,
        'target_property': {'id': str(target.id), 'name': target.name} if target is not None else None,
        'progress': {'done': sum(1 for step in counted if step['done']), 'total': len(counted)},
        'next_step': next_step,
        'steps': steps,
    }
