from rest_framework.routers import SimpleRouter

from .views import AdmissionViewSet, ResidentViewSet

router = SimpleRouter()
router.register('residents', ResidentViewSet, basename='resident')
router.register('admissions', AdmissionViewSet, basename='admission')

urlpatterns = router.urls
