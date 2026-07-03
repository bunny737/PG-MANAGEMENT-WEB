from rest_framework.routers import SimpleRouter

from .views import DiscountViewSet, InvoiceViewSet

router = SimpleRouter()
router.register('discounts', DiscountViewSet, basename='discount')
router.register('invoices', InvoiceViewSet, basename='invoice')

urlpatterns = router.urls
