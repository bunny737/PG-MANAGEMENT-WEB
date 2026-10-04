from rest_framework.routers import SimpleRouter

from .views import NotificationHistoryViewSet, NotificationPreferenceViewSet, PushSubscriptionViewSet

router = SimpleRouter()
router.register('notifications/history', NotificationHistoryViewSet, basename='notification-history')
router.register('notifications/preferences', NotificationPreferenceViewSet, basename='notification-preference')
router.register('notifications/push-subscriptions', PushSubscriptionViewSet, basename='push-subscription')

urlpatterns = router.urls
