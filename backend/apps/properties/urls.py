from rest_framework.routers import SimpleRouter

from .views import (
    BedViewSet,
    BuildingViewSet,
    FeatureCatalogViewSet,
    FloorViewSet,
    PropertyStaffAssignmentViewSet,
    PropertyViewSet,
    RoomViewSet,
    TenantFeatureViewSet,
)

router = SimpleRouter()
router.register('properties', PropertyViewSet, basename='property')
router.register('buildings', BuildingViewSet, basename='building')
router.register('floors', FloorViewSet, basename='floor')
router.register('rooms', RoomViewSet, basename='room')
router.register('beds', BedViewSet, basename='bed')
router.register('feature-catalog', FeatureCatalogViewSet, basename='feature-catalog')
router.register('tenant-features', TenantFeatureViewSet, basename='tenant-feature')
router.register('staff-property-assignments', PropertyStaffAssignmentViewSet, basename='property-staff-assignment')

urlpatterns = router.urls
