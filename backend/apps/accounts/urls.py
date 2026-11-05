from django.urls import path

from . import resident_auth, views

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='auth-signup'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='auth-verify-email'),
    path('resend-verification/', views.ResendVerificationView.as_view(), name='auth-resend-verification'),
    path('login/', views.LoginView.as_view(), name='auth-login'),
    path('login-phone/', views.PhoneLoginView.as_view(), name='auth-login-phone'),
    path('token/refresh/', views.RefreshView.as_view(), name='auth-token-refresh'),
    path('otp/request/', views.OtpRequestView.as_view(), name='auth-otp-request'),
    path('otp/verify/', views.OtpVerifyView.as_view(), name='auth-otp-verify'),
    path('otp/email/request/', views.EmailOtpRequestView.as_view(), name='auth-otp-email-request'),
    path('otp/email/verify/', views.EmailOtpVerifyView.as_view(), name='auth-otp-email-verify'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='auth-password-reset'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='auth-password-reset-confirm'),
    path('password/change/', views.PasswordChangeView.as_view(), name='auth-password-change'),
    path('me/', views.MeView.as_view(), name='auth-me'),
    path('account/deletion/', views.AccountDeletionView.as_view(), name='auth-account-deletion'),
    path('account/deletion/otp/', views.AccountDeletionOtpView.as_view(), name='auth-account-deletion-otp'),

    # Resident app accounts (Module 26): their own pool, endpoints and throttles.
    path('resident/signup/', resident_auth.ResidentSignupView.as_view(), name='resident-signup'),
    path('resident/login/', resident_auth.ResidentLoginView.as_view(), name='resident-login'),
    path('resident/otp/email/request/', resident_auth.ResidentEmailCodeRequestView.as_view(), name='resident-otp-email-request'),
    path('resident/otp/email/verify/', resident_auth.ResidentEmailCodeVerifyView.as_view(), name='resident-otp-email-verify'),
    path('resident/password-reset/', resident_auth.ResidentPasswordResetRequestView.as_view(), name='resident-password-reset'),
    path('resident/password-reset/confirm/', resident_auth.ResidentPasswordResetConfirmView.as_view(), name='resident-password-reset-confirm'),
]
