from rest_framework.routers import SimpleRouter

from .views import DiscountViewSet

router = SimpleRouter()
router.register('discounts', DiscountViewSet, basename='discount')

urlpatterns = router.urls
