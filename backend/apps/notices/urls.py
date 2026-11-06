from rest_framework.routers import SimpleRouter

from .views import AnnouncementViewSet, FoodHolidayViewSet

router = SimpleRouter()
router.register('notices', AnnouncementViewSet, basename='notice')
router.register('food-holidays', FoodHolidayViewSet, basename='food-holiday')

urlpatterns = router.urls
