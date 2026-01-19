from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.admin_api.views import (
    AdminStatsViews, UserViewSet, OrganizationViewSet,
    admin_login, admin_global_search,
    all_jobs, all_chatbots, all_sites,
    job_detail, job_action, export_jobs,
    audit_logs, bulk_user_action, export_users, impersonate_user,
    system_health, system_queues, system_metrics,
    get_maintenance_mode, set_maintenance_mode,
    admin_error_logs,
    announcements_list, announcement_detail,
    broadcast_email, email_segments,
    feature_flag_list, feature_flag_detail, check_feature_flag,
    waitlist_list, waitlist_detail, waitlist_stats,
    platform_analytics, tier_stats, get_tier_config, update_org_tier,
    feedback_list, feedback_detail, feedback_stats, feedback_export, feedback_bulk_action,
    faq_categories, faq_category_detail, faqs_list, faq_detail,
    help_articles_list, help_article_detail, help_center_stats,
    admin_leads_dashboard, admin_query_analytics, admin_geo_analytics,
    # 2FA endpoints
    twofa_status, twofa_setup, twofa_verify, twofa_disable,
    twofa_regenerate_backup_codes, twofa_login_verify,
    # Alerting endpoints
    alert_rules_list, alert_rule_detail, alert_rule_test,
    alert_notifications_list, system_alerts_list, system_alert_detail,
    system_alert_acknowledge, system_alert_resolve, alert_stats
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='admin-users')
router.register(r'organizations', OrganizationViewSet, basename='admin-organizations')

urlpatterns = [
    # Admin Authentication (no auth required - validates credentials internally)
    path('auth/login/', admin_login, name='admin-login'),

    # Two-Factor Authentication (2FA)
    path('auth/2fa/status/', twofa_status, name='admin-2fa-status'),
    path('auth/2fa/setup/', twofa_setup, name='admin-2fa-setup'),
    path('auth/2fa/verify/', twofa_verify, name='admin-2fa-verify'),
    path('auth/2fa/disable/', twofa_disable, name='admin-2fa-disable'),
    path('auth/2fa/backup-codes/', twofa_regenerate_backup_codes, name='admin-2fa-backup-codes'),
    path('auth/2fa/login/', twofa_login_verify, name='admin-2fa-login'),

    # Stats endpoints (ViewSet actions)
    path('stats/overview/', AdminStatsViews.as_view({'get': 'overview'}), name='admin-stats-overview'),
    path('stats/growth/', AdminStatsViews.as_view({'get': 'growth'}), name='admin-stats-growth'),
    path('stats/revenue/', AdminStatsViews.as_view({'get': 'revenue'}), name='admin-stats-revenue'),
    path('stats/usage/', AdminStatsViews.as_view({'get': 'usage'}), name='admin-stats-usage'),
    path('stats/plans/', AdminStatsViews.as_view({'get': 'plans'}), name='admin-stats-plans'),
    
    # Global Search
    path('search/', admin_global_search, name='admin-global-search'),
    
    # Global list endpoints (all resources across platform)
    path('jobs/', all_jobs, name='admin-all-jobs'),
    path('jobs/export/', export_jobs, name='admin-export-jobs'),
    path('jobs/<uuid:job_id>/', job_detail, name='admin-job-detail'),
    path('jobs/<uuid:job_id>/action/', job_action, name='admin-job-action'),
    path('chatbots/', all_chatbots, name='admin-all-chatbots'),
    path('sites/', all_sites, name='admin-all-sites'),
    
    # Audit and Security endpoints
    path('audit-logs/', audit_logs, name='admin-audit-logs'),
    
    # Bulk operations
    path('users/bulk-action/', bulk_user_action, name='admin-bulk-user-action'),
    path('users/export/', export_users, name='admin-export-users'),
    
    # Impersonation
    path('users/<uuid:user_id>/impersonate/', impersonate_user, name='admin-impersonate-user'),
    
    # System Health & Monitoring
    path('system/health/', system_health, name='admin-system-health'),
    path('system/queues/', system_queues, name='admin-system-queues'),
    path('system/metrics/', system_metrics, name='admin-system-metrics'),
    path('system/maintenance/', get_maintenance_mode, name='admin-maintenance-get'),
    path('system/maintenance/set/', set_maintenance_mode, name='admin-maintenance-set'),

    # Error Logs
    path('logs/errors/', admin_error_logs, name='admin-error-logs'),

    # Announcements
    path('announcements/', announcements_list, name='admin-announcements-list'),
    path('announcements/<uuid:announcement_id>/', announcement_detail, name='admin-announcement-detail'),

    # Broadcast Email
    path('broadcast-email/', broadcast_email, name='admin-broadcast-email'),
    path('broadcast-email/segments/', email_segments, name='admin-email-segments'),

    # Feature Flags
    path('feature-flags/', feature_flag_list, name='admin-feature-flags'),
    path('feature-flags/check/', check_feature_flag, name='check-feature-flag'),
    path('feature-flags/<uuid:pk>/', feature_flag_detail, name='admin-feature-flag-detail'),

    # Waitlist/Upgrade Interest Management
    path('waitlist/', waitlist_list, name='admin-waitlist-list'),
    path('waitlist/stats/', waitlist_stats, name='admin-waitlist-stats'),
    path('waitlist/<uuid:interest_id>/', waitlist_detail, name='admin-waitlist-detail'),

    # Platform Analytics
    path('analytics/', platform_analytics, name='admin-platform-analytics'),
    path('analytics/tiers/', tier_stats, name='admin-tier-stats'),

    # Admin Leads Dashboard
    path('leads/', admin_leads_dashboard, name='admin-leads-dashboard'),
    path('leads/queries/', admin_query_analytics, name='admin-query-analytics'),
    path('leads/geo/', admin_geo_analytics, name='admin-geo-analytics'),

    # Tier Configuration
    path('tiers/config/', get_tier_config, name='admin-tier-config'),
    path('organizations/<uuid:org_id>/tier/', update_org_tier, name='admin-update-org-tier'),

    # Feedback Management
    path('feedback/', feedback_list, name='admin-feedback-list'),
    path('feedback/stats/', feedback_stats, name='admin-feedback-stats'),
    path('feedback/export/', feedback_export, name='admin-feedback-export'),
    path('feedback/bulk-action/', feedback_bulk_action, name='admin-feedback-bulk-action'),
    path('feedback/<uuid:feedback_id>/', feedback_detail, name='admin-feedback-detail'),

    # Help Center - FAQ Categories
    path('help/categories/', faq_categories, name='admin-faq-categories'),
    path('help/categories/<uuid:category_id>/', faq_category_detail, name='admin-faq-category-detail'),

    # Help Center - FAQs
    path('help/faqs/', faqs_list, name='admin-faqs-list'),
    path('help/faqs/<uuid:faq_id>/', faq_detail, name='admin-faq-detail'),

    # Help Center - Articles
    path('help/articles/', help_articles_list, name='admin-help-articles-list'),
    path('help/articles/<uuid:article_id>/', help_article_detail, name='admin-help-article-detail'),

    # Help Center Stats
    path('help/stats/', help_center_stats, name='admin-help-center-stats'),

    # Alerting System
    path('alerts/stats/', alert_stats, name='admin-alert-stats'),
    path('alerts/rules/', alert_rules_list, name='admin-alert-rules'),
    path('alerts/rules/<uuid:rule_id>/', alert_rule_detail, name='admin-alert-rule-detail'),
    path('alerts/rules/<uuid:rule_id>/test/', alert_rule_test, name='admin-alert-rule-test'),
    path('alerts/notifications/', alert_notifications_list, name='admin-alert-notifications'),
    path('alerts/system/', system_alerts_list, name='admin-system-alerts'),
    path('alerts/system/<uuid:alert_id>/', system_alert_detail, name='admin-system-alert-detail'),
    path('alerts/system/<uuid:alert_id>/acknowledge/', system_alert_acknowledge, name='admin-system-alert-acknowledge'),
    path('alerts/system/<uuid:alert_id>/resolve/', system_alert_resolve, name='admin-system-alert-resolve'),

    # Router endpoints (Users, Orgs with nested actions)
    path('', include(router.urls)),
]
