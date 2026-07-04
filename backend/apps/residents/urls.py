from rest_framework.routers import SimpleRouter

from .views import (
    AbscondedRecordViewSet,
    AdmissionViewSet,
    AllocationViewSet,
    BlacklistEntryViewSet,
    ResidentViewSet,
    TransferViewSet,
    VacateViewSet,
)

router = SimpleRouter()
router.register('residents', ResidentViewSet, basename='resident')
router.register('admissions', AdmissionViewSet, basename='admission')
router.register('allocations', AllocationViewSet, basename='allocation')
router.register('transfers', TransferViewSet, basename='transfer')
router.register('vacates', VacateViewSet, basename='vacate')
router.register('absconded-records', AbscondedRecordViewSet, basename='absconded-record')
router.register('blacklist-entries', BlacklistEntryViewSet, basename='blacklist-entry')

urlpatterns = router.urls
