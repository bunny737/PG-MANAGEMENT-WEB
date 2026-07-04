from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import PlanViewSet, RazorpayWebhookView, SubscriptionViewSet

router = SimpleRouter()
router.register('plans', PlanViewSet, basename='plan')
router.register('subscriptions', SubscriptionViewSet, basename='subscription')

# The webhook path must come before router.urls — otherwise the router's
# `subscriptions/{tenant_id}/` detail pattern greedily matches
# `subscriptions/webhook/` first (tenant_id='webhook') and 401s.
urlpatterns = [
    path('subscriptions/webhook/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
] + router.urls
