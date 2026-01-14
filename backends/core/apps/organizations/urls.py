from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'orgs', views.OrganizationViewSet, basename='organization')

urlpatterns = [
    path('', include(router.urls)),
    path('me/organizations/', views.user_organizations, name='user-organizations'),
    path('orgs/<uuid:org_id>/memberships/', views.MembershipViewSet.as_view({'get': 'list', 'post': 'create'}), name='membership-list'),
    path('orgs/<uuid:org_id>/memberships/<uuid:pk>/', views.MembershipViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}), name='membership-detail'),
]
