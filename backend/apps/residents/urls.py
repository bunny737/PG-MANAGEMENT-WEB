from django.urls import path
from rest_framework.routers import SimpleRouter

from . import access_views
from .views import (
    AbscondedRecordViewSet,
    AdmissionViewSet,
    AllocationViewSet,
    BlacklistEntryViewSet,
    ResidentViewSet,
    TransferViewSet,
    VacateViewSet,
)

router = SimpleRouter()
router.register('residents', ResidentViewSet, basename='resident')
router.register('admissions', AdmissionViewSet, basename='admission')
router.register('allocations', AllocationViewSet, basename='allocation')
router.register('transfers', TransferViewSet, basename='transfer')
router.register('vacates', VacateViewSet, basename='vacate')
router.register('absconded-records', AbscondedRecordViewSet, basename='absconded-record')
router.register('blacklist-entries', BlacklistEntryViewSet, basename='blacklist-entry')
router.register('residency-link-requests', access_views.ResidencyLinkRequestViewSet, basename='residency-link-request')

# Resident app access (Module 26). Staff side:
urlpatterns = [
    path('residents/<uuid:pk>/app-access/', access_views.ResidentAppAccessView.as_view(), name='resident-app-access'),
    path('residents/<uuid:pk>/app-access/revoke/', access_views.ResidentAppAccessRevokeView.as_view(), name='resident-app-access-revoke'),
    path('residents/<uuid:pk>/app-invite/', access_views.ResidentAppInviteView.as_view(), name='resident-app-invite'),
    path('residents/<uuid:pk>/app-invite/cancel/', access_views.ResidentAppInviteCancelView.as_view(), name='resident-app-invite-cancel'),
    path('properties/<uuid:pk>/join-code/', access_views.PropertyJoinCodeView.as_view(), name='property-join-code'),
    path('properties/<uuid:pk>/join-code/rotate/', access_views.PropertyJoinCodeRotateView.as_view(), name='property-join-code-rotate'),
    # The person's side (a resident-pool account; own serializers):
    path('me/residencies/', access_views.MyResidenciesView.as_view(), name='my-residencies'),
    path('me/join-codes/<str:code>/', access_views.JoinCodeLookupView.as_view(), name='my-join-code-lookup'),
    path('me/link-requests/', access_views.MyLinkRequestsView.as_view(), name='my-link-requests'),
    path('me/link-requests/<uuid:pk>/cancel/', access_views.MyLinkRequestCancelView.as_view(), name='my-link-request-cancel'),
    path('me/invites/accept/', access_views.InviteAcceptView.as_view(), name='my-invite-accept'),
] + router.urls
