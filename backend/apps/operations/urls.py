from rest_framework.routers import SimpleRouter

from .views import ComplaintViewSet

router = SimpleRouter()
router.register('complaints', ComplaintViewSet, basename='complaint')

urlpatterns = router.urls
