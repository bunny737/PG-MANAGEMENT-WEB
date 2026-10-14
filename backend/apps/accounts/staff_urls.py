from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CurrentTenantView, StaffModuleAccessView, StaffViewSet

router = SimpleRouter()
router.register('staff', StaffViewSet, basename='staff')

urlpatterns = router.urls + [
    path('staff/<uuid:pk>/module-access/', StaffModuleAccessView.as_view(), name='staff-module-access'),
    path('tenants/current/', CurrentTenantView.as_view(), name='tenant-current'),
]
