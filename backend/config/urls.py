from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core import health

urlpatterns = [
    path('health/', health.liveness, name='health-liveness'),
    path('health/ready/', health.readiness, name='health-readiness'),
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # App routes — each app's urls.py starts as a stub and grows module by module
    path('api/v1/auth/',   include('apps.accounts.urls')),
    path('api/v1/',        include('apps.accounts.staff_urls')),
    path('api/v1/',        include('apps.properties.urls')),
    path('api/v1/',        include('apps.residents.urls')),
    path('api/v1/',        include('apps.billing.urls')),
    path('api/v1/',        include('apps.operations.urls')),
    path('api/v1/',        include('apps.subscriptions.urls')),
    path('api/v1/',        include('apps.reporting.urls')),
    path('api/v1/',        include('apps.audit.urls')),
    path('api/v1/',        include('apps.notifications.urls')),
    path('api/v1/',        include('apps.devices.urls')),
    path('api/v1/',        include('apps.expenses.urls')),
    path('api/v1/',        include('apps.core.urls')),
]

if settings.DEBUG:
    # Local-filesystem media (uploaded documents/images) has no dev web
    # server otherwise — in prod files live in a private GCS bucket and are
    # served as signed URLs (apps.core.storage), so this is a dev-only fallback.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
