from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CashMovementView, DiscountViewSet, InvoiceViewSet, PaymentViewSet

router = SimpleRouter()
router.register('discounts', DiscountViewSet, basename='discount')
router.register('invoices', InvoiceViewSet, basename='invoice')
router.register('payments', PaymentViewSet, basename='payment')

urlpatterns = router.urls + [
    path('cash-movements/', CashMovementView.as_view(), name='cash-movements'),
]
