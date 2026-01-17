"""
URL configuration for analytics API endpoints.

All endpoints are prefixed with /v1/frontend/analytics/
"""

from django.urls import path
from apps.analytics import views

app_name = 'analytics'

urlpatterns = [
    # Leads endpoints
    path('leads/', views.leads_dashboard, name='leads-dashboard'),
    path('leads/export/', views.leads_export, name='leads-export'),
    path('leads/<uuid:lead_id>/', views.lead_detail, name='lead-detail'),

    # Reports endpoints
    path('reports/', views.weekly_reports_list, name='reports-list'),
    path('reports/generate/', views.generate_report, name='reports-generate'),
    path('reports/preferences/', views.report_preferences, name='reports-preferences'),
    path('reports/<uuid:report_id>/', views.weekly_report_detail, name='report-detail'),

    # Enhanced Analytics endpoints
    path('enhanced/', views.enhanced_analytics, name='enhanced-analytics'),
    path('return-visitors/', views.return_visitors_analytics, name='return-visitors'),
    path('content-gaps/', views.content_gaps_analytics, name='content-gaps'),
    path('peak-usage/', views.peak_usage_analytics, name='peak-usage'),
    path('conversation-quality/', views.conversation_quality_analytics, name='conversation-quality'),
]
