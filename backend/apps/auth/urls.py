from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # Authentication
    path('signup/', views.UserRegistrationView.as_view(), name='user-signup'),
    path('login/', views.UserLoginView.as_view(), name='user-login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='verify-email'),
    path('resend-otp/', views.ResendOTPView.as_view(), name='resend-otp'),

    # User Profile Management
    path('me/', views.user_profile, name='user-profile'),
    path('profile/update/', views.update_profile, name='update-profile'),
    path('password/change/', views.change_password, name='change-password'),
    path('email/update/', views.update_email, name='update-email'),
    path('email/verify-change/', views.verify_email_change, name='verify-email-change'),
    path('account/delete/', views.delete_account, name='delete-account'),
    path('preferences/', views.user_preferences, name='user-preferences'),
    path('feedback/', views.submit_feedback, name='submit-feedback'),
    path('support/', views.submit_support_request, name='submit-support-request'),
    path('test-email/', views.send_test_email, name='send-test-email'),

    # API Key Management
    path('api-keys/', views.APIKeyViewSet.as_view({'get': 'list', 'post': 'create'}), name='api-key-list'),
    path('api-keys/<uuid:pk>/', views.APIKeyViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}), name='api-key-detail'),
    path('api-keys/<uuid:pk>/rotate/', views.APIKeyViewSet.as_view({'post': 'rotate'}), name='api-key-rotate'),
]
