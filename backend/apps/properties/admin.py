from django import forms
from django.contrib import admin

from apps.audit import log as audit_log

from . import feature_services
from .models import (
    Bed,
    Building,
    FeatureCatalog,
    Floor,
    Property,
    PropertyFeature,
    PropertyImage,
    PropertySettings,
    PropertyStaffAssignment,
    Room,
    TenantFeature,
)

admin.site.register(Property)
admin.site.register(PropertyImage)
admin.site.register(Building)
admin.site.register(Floor)
admin.site.register(Room)
admin.site.register(Bed)
admin.site.register(PropertyStaffAssignment)
admin.site.register(PropertySettings)


# The three Module 18 models are deliberately not bare-registered like the
# ones above: a hand edit would bypass the feature_services invariants.


@admin.register(FeatureCatalog)
class FeatureCatalogAdmin(admin.ModelAdmin):
    """Reorder, shortlist or retire platform features. Adding one is a code
    change (seed migration + a translatable label in feature_catalog.py), so
    there is no add form — a code with no label could never be translated."""

    list_display = ('code', 'category', 'display_order', 'is_popular', 'is_active')
    list_editable = ('display_order', 'is_popular', 'is_active')
    list_filter = ('category', 'is_active', 'is_popular')
    search_fields = ('code',)
    readonly_fields = ('code', 'category')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = {name: form.initial.get(name) for name in ('display_order', 'is_popular', 'is_active')}
        super().save_model(request, obj, form, change)
        after = {'display_order': obj.display_order, 'is_popular': obj.is_popular, 'is_active': obj.is_active}
        if before != after:
            # Reaches every tenant (invariant 9).
            audit_log.record(
                action='feature_catalog.updated', actor=request.user, tenant_id=None, obj=obj,
                before=before, after=after, request=request,
            )


class TenantFeatureAdminForm(forms.ModelForm):
    class Meta:
        model = TenantFeature
        fields = ['label', 'is_active']


@admin.register(TenantFeature)
class TenantFeatureAdmin(admin.ModelAdmin):
    form = TenantFeatureAdminForm
    list_display = ('label', 'tenant_id', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('label',)

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        # Same collision checks, slug recompute and audit entry as the API.
        feature_services.update_tenant_feature(
            TenantFeature.objects.get(pk=obj.pk),
            label=form.cleaned_data['label'], is_active=form.cleaned_data['is_active'],
            actor=request.user, request=request,
        )


@admin.register(PropertyFeature)
class PropertyFeatureAdmin(admin.ModelAdmin):
    list_display = ('property', 'building', 'catalog_feature', 'tenant_feature', 'is_available', 'is_paid')
    list_filter = ('is_available', 'is_paid')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
