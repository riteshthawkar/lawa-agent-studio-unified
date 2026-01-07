from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'usage', views.UsageViewSet, basename='usage')

urlpatterns = [
    path('', include(router.urls)),
    path('orgs/<uuid:org_id>/usage/', views.organization_usage, name='organization-usage'),
    path('orgs/<uuid:org_id>/quotas/', views.organization_quotas, name='organization-quotas'),
    path('orgs/<uuid:org_id>/quotas', views.create_quota, name='create-quota'),
    # Usage summary and waitlist
    path('usage-summary/', views.UsageSummaryView.as_view(), name='usage-summary'),
    path('waitlist/', views.JoinWaitlistView.as_view(), name='join-waitlist'),
]
