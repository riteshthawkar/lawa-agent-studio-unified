from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'webhooks', views.WebhookViewSet, basename='webhook')

urlpatterns = [
    # Explicit paths MUST come before router to avoid being caught by <pk> pattern
    path('webhooks/indexing/', views.indexing_webhook, name='indexing-webhook'),
    path('webhooks/<uuid:webhook_id>/retry/', views.retry_webhook, name='retry-webhook'),
    path('orgs/<uuid:org_id>/audit-logs/', views.audit_logs, name='audit-logs'),
    # Router patterns last
    path('', include(router.urls)),
]
