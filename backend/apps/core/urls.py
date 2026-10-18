from django.urls import path

from .views import SupportContactView

urlpatterns = [
    path('support/', SupportContactView.as_view(), name='support-contact'),
]
