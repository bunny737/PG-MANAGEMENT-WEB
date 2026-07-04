from rest_framework.routers import SimpleRouter

from .views import ComplaintViewSet, VisitorViewSet

router = SimpleRouter()
router.register('complaints', ComplaintViewSet, basename='complaint')
router.register('visitors', VisitorViewSet, basename='visitor')

urlpatterns = router.urls
