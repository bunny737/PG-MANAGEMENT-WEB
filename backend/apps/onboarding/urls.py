from django.urls import path

from .views import ChecklistDismissView, ChecklistView, TutorialVideoListView

urlpatterns = [
    path('onboarding/checklist/', ChecklistView.as_view(), name='onboarding-checklist'),
    path('onboarding/checklist/dismiss/', ChecklistDismissView.as_view(), name='onboarding-checklist-dismiss'),
    path('help/videos/', TutorialVideoListView.as_view(), name='help-videos'),
]
