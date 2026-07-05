from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
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
]

if settings.DEBUG:
    # Local-filesystem media (uploaded documents/images) has no dev web
    # server otherwise — S3 handles this itself once AWS_STORAGE_BUCKET_NAME
    # is configured (see settings/base.py), so this is a dev-only fallback.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
