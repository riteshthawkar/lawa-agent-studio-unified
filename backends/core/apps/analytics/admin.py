"""
Django admin configuration for analytics models.
"""

from django.contrib import admin
from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences


@admin.register(LeadScore)
class LeadScoreAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'priority', 'total_score', 'detected_intent',
        'geo_location', 'device_type', 'session_date', 'created_at'
    ]
    list_filter = ['priority', 'detected_intent', 'device_type', 'session_date']
    search_fields = ['id', 'geo_location', 'conversation_summary']
    readonly_fields = [
        'id', 'session', 'chatbot', 'org_id', 'engagement_score',
        'intent_score', 'total_score', 'priority', 'detected_intent',
        'key_questions', 'conversation_summary', 'source_url',
        'geo_location', 'device_type', 'session_date',
        'session_duration_seconds', 'message_count',
        'had_positive_feedback', 'had_negative_feedback',
        'created_at', 'updated_at'
    ]
    ordering = ['-total_score', '-session_date']
    date_hierarchy = 'session_date'


@admin.register(WeeklyLeadsReport)
class WeeklyLeadsReportAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'org', 'user', 'chatbot', 'week_start', 'week_end',
        'total_leads', 'hot_leads', 'warm_leads', 'cold_leads',
        'email_sent', 'created_at'
    ]
    list_filter = ['email_sent', 'week_start']
    search_fields = ['user__email', 'org__name']
    readonly_fields = [
        'id', 'org', 'user', 'chatbot', 'week_start', 'week_end',
        'total_sessions', 'total_leads', 'hot_leads', 'warm_leads',
        'cold_leads', 'leads_change_percent', 'sessions_change_percent',
        'report_data', 'email_sent', 'email_sent_at', 'email_error',
        'created_at', 'updated_at'
    ]
    ordering = ['-week_start', '-created_at']
    date_hierarchy = 'week_start'


@admin.register(ReportPreferences)
class ReportPreferencesAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'org', 'weekly_report_enabled',
        'report_day', 'report_hour', 'timezone',
        'notify_hot_leads_immediately', 'created_at'
    ]
    list_filter = ['weekly_report_enabled', 'report_day', 'notify_hot_leads_immediately']
    search_fields = ['user__email', 'org__name']
    ordering = ['user__email']
