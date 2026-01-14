from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import monitoring

router = DefaultRouter()
router.register(r'health', views.BaseViewSet, basename='health')

urlpatterns = [
    path('', include(router.urls)),
    path('health/', monitoring.health_check, name='health-check'),
    path('metrics/', monitoring.metrics, name='metrics'),
    path('system-info/', monitoring.system_info, name='system-info'),
    path('record-metric/', monitoring.record_metric, name='record-metric'),
]
