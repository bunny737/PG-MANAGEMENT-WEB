from rest_framework.routers import SimpleRouter

from .views import (
    AdmissionViewSet,
    AllocationViewSet,
    ResidentViewSet,
    TransferViewSet,
)

router = SimpleRouter()
router.register('residents', ResidentViewSet, basename='resident')
router.register('admissions', AdmissionViewSet, basename='admission')
router.register('allocations', AllocationViewSet, basename='allocation')
router.register('transfers', TransferViewSet, basename='transfer')

urlpatterns = router.urls
