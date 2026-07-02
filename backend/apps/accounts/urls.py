from django.urls import path

from . import views

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='auth-signup'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='auth-verify-email'),
    path('resend-verification/', views.ResendVerificationView.as_view(), name='auth-resend-verification'),
    path('login/', views.LoginView.as_view(), name='auth-login'),
    path('token/refresh/', views.RefreshView.as_view(), name='auth-token-refresh'),
    path('otp/request/', views.OtpRequestView.as_view(), name='auth-otp-request'),
    path('otp/verify/', views.OtpVerifyView.as_view(), name='auth-otp-verify'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='auth-password-reset'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='auth-password-reset-confirm'),
    path('me/', views.MeView.as_view(), name='auth-me'),
]
