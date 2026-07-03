from rest_framework.routers import SimpleRouter

from .views import ResidentViewSet

router = SimpleRouter()
router.register('residents', ResidentViewSet, basename='resident')

urlpatterns = router.urls
