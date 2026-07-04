from rest_framework.routers import SimpleRouter

from .views import DiscountViewSet, InvoiceViewSet, PaymentViewSet

router = SimpleRouter()
router.register('discounts', DiscountViewSet, basename='discount')
router.register('invoices', InvoiceViewSet, basename='invoice')
router.register('payments', PaymentViewSet, basename='payment')

urlpatterns = router.urls
