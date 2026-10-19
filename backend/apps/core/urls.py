from django.urls import path

from .views import ContactMessageView, SupportContactView

urlpatterns = [
    path('support/', SupportContactView.as_view(), name='support-contact'),
    path('public/contact/', ContactMessageView.as_view(), name='contact-message'),
]
