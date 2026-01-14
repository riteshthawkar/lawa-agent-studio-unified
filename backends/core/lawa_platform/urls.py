from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from apps.core.health_views import health_check, health_detailed, health_ready, health_live

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Health Check Endpoints
    path('health/', health_check, name='health'),
    path('health/detailed/', health_detailed, name='health_detailed'),
    path('health/ready/', health_ready, name='health_ready'),
    path('health/live/', health_live, name='health_live'),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # API v1
    path('v1/', include([
        path('auth/', include('apps.auth.urls')),
        path('frontend/', include('apps.frontend.urls')),
        path('support/', include('apps.support.urls')),
        path('payments/', include('apps.payments.urls')),
        path('admin/', include('apps.admin_api.urls')),
        path('', include('apps.organizations.urls')),
        path('', include('apps.sites.urls')),
        path('', include('apps.indexing.urls')),
        path('', include('apps.chatbot.urls')),
        path('', include('apps.chat.urls')),
        path('', include('apps.usage.urls')),
        path('', include('apps.webhooks.urls')),
        path('', include('apps.core.urls')),
    ])),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)