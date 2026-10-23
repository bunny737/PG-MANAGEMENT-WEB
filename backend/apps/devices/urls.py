from django.urls import path

from .views import DeviceRegisterView, DeviceUnlinkUserView, VersionPolicyView

urlpatterns = [
    path('app/version-policy/', VersionPolicyView.as_view(), name='app-version-policy'),
    path('devices/', DeviceRegisterView.as_view(), name='device-register'),
    path('devices/<uuid:installation_id>/user/', DeviceUnlinkUserView.as_view(), name='device-unlink-user'),
]
