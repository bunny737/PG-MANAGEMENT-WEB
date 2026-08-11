from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CurrentTenantView, StaffViewSet

router = SimpleRouter()
router.register('staff', StaffViewSet, basename='staff')

urlpatterns = router.urls + [
    path('tenants/current/', CurrentTenantView.as_view(), name='tenant-current'),
]
