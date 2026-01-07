from django.urls import path
from . import views, management_views

urlpatterns = [
    # Dashboard endpoints
    path('dashboard/stats/', views.dashboard_stats, name='dashboard-stats'),
    path('analytics/', views.analytics_data, name='analytics-data'),
    path('analytics/queries/', views.query_analytics, name='query-analytics'),
    path('analytics/citations/', views.citation_analytics, name='citation-analytics'),
    path('analytics/geo/', views.geo_analytics, name='geo-analytics'),
    path('analytics/feedback/', views.feedback_details, name='feedback-details'),
    
    # Premium Analytics endpoints (Premium tier and above)
    path('analytics/sentiment/', views.sentiment_analytics, name='sentiment-analytics'),
    path('analytics/cost/', views.cost_analytics, name='cost-analytics'),
    path('analytics/retention/', views.retention_analytics, name='retention-analytics'),
    
    # Enterprise Analytics endpoints (Enterprise tier only)
    path('analytics/cohort/', views.cohort_analytics, name='cohort-analytics'),
    path('analytics/predictive/', views.predictive_analytics, name='predictive-analytics'),
    path('analytics/realtime/', views.realtime_dashboard, name='realtime-dashboard'),

    # Management endpoints (list/get)
    path('sites/', views.sites_management, name='sites-management'),
    path('sites/<uuid:site_id>/', views.site_detail, name='site-detail'),
    path('indexing-jobs/', views.indexing_jobs_management, name='indexing-jobs-management'),
    path('chatbots/', views.chatbots_management, name='chatbots-management'),

    # Site management
    path('sites/create/', management_views.create_site, name='create-site'),
    path('sites/<uuid:site_id>/update/', management_views.update_site, name='update-site'),
    path('sites/<uuid:site_id>/delete/', management_views.delete_site, name='delete-site'),
    path('sites/<uuid:site_id>/indexing-jobs/create/', management_views.create_indexing_job, name='create-indexing-job'),
    path('sites/<uuid:site_id>/chatbots/create/', management_views.create_chatbot, name='create-chatbot'),

    # Indexing Job History endpoints
    path('sites/<uuid:site_id>/indexing-jobs/history/', views.site_indexing_job_history, name='site-indexing-job-history'),
    path('indexing-jobs/<uuid:job_id>/', views.indexing_job_detail_frontend, name='indexing-job-detail-frontend'),
    path('indexing-jobs/<uuid:job_id>/retry/', views.retry_indexing_job, name='retry-indexing-job'),

    # Knowledge Base Search endpoint
    path('sites/<uuid:site_id>/search/', views.search_knowledge_base, name='site-knowledge-base-search'),

    # Chatbot management
    path('chatbots/<uuid:chatbot_id>/', management_views.get_or_update_chatbot, name='get-or-update-chatbot'),
    path('chatbots/<uuid:chatbot_id>/delete/', management_views.delete_chatbot, name='delete-chatbot'),

    # User profile
    path('user/profile/', views.user_profile, name='user-profile'),

    # Bulk actions
    path('bulk-actions/', views.bulk_actions, name='bulk-actions'),
]
