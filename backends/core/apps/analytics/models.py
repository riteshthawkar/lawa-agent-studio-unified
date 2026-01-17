"""
Analytics models for lead scoring and weekly reports.

This module provides:
- LeadScore: Derived lead quality scores from chat sessions
- WeeklyLeadsReport: Stored weekly reports for dashboard and email delivery
- ReportPreferences: User preferences for report scheduling and content
"""

import uuid
from django.db import models
from django.conf import settings
from apps.core.models import BaseModel


class LeadScore(BaseModel):
    """
    Derived lead from chat session engagement.

    Scores are calculated based on:
    - Engagement signals (message count, duration, feedback)
    - Intent signals (pricing, demo, contact keywords)
    - Conversation quality metrics
    """
    session = models.OneToOneField(
        'chat.ChatSession',
        on_delete=models.CASCADE,
        related_name='lead_score',
        help_text="The chat session this lead score is derived from"
    )
    chatbot = models.ForeignKey(
        'chatbot.Chatbot',
        on_delete=models.CASCADE,
        related_name='lead_scores',
        help_text="The chatbot that handled this conversation"
    )
    org_id = models.UUIDField(
        db_index=True,
        help_text="Organization ID for multi-tenancy filtering"
    )

    # Scoring components
    engagement_score = models.IntegerField(
        default=0,
        help_text="Score based on engagement signals (messages, duration, feedback)"
    )
    intent_score = models.IntegerField(
        default=0,
        help_text="Score based on high-intent keywords detected"
    )
    total_score = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Combined score (engagement + intent)"
    )
    priority = models.CharField(
        max_length=10,
        choices=[
            ('hot', 'Hot'),
            ('warm', 'Warm'),
            ('cold', 'Cold'),
        ],
        default='cold',
        db_index=True,
        help_text="Lead priority classification based on total score"
    )

    # Extracted information
    detected_intent = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        help_text="Primary detected intent (pricing, demo, contact, support, etc.)"
    )
    key_questions = models.JSONField(
        default=list,
        blank=True,
        help_text="List of important questions asked by the visitor"
    )
    conversation_summary = models.TextField(
        blank=True,
        default='',
        help_text="Brief summary of the conversation"
    )

    # Context from session
    source_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Referrer URL where the conversation started"
    )
    geo_location = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Geographic location (city, country)"
    )
    device_type = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Device type (mobile, tablet, desktop)"
    )

    # Timing
    session_date = models.DateField(
        db_index=True,
        help_text="Date of the session (for date-range queries)"
    )
    session_duration_seconds = models.IntegerField(
        default=0,
        help_text="Duration of the session in seconds"
    )
    message_count = models.IntegerField(
        default=0,
        help_text="Total number of messages in the session"
    )

    # Feedback
    had_positive_feedback = models.BooleanField(
        default=False,
        help_text="Whether the session had any positive feedback (likes)"
    )
    had_negative_feedback = models.BooleanField(
        default=False,
        help_text="Whether the session had any negative feedback (dislikes)"
    )

    # LLM Analysis Insights (populated when LLM scoring is used)
    llm_insights = models.JSONField(
        null=True,
        blank=True,
        help_text="""
        LLM-extracted insights structure:
        {
            "analyzed_by_llm": true,
            "model_used": "gpt-4o-mini",
            "intent": {
                "primary": "pricing_inquiry",
                "confidence": 85,
                "buying_signals": ["asked about pricing", "mentioned timeline"],
                "objections": ["budget concerns"]
            },
            "entities": {
                "company_name": "Acme Inc",
                "job_title": "CTO",
                "team_size": "50-100",
                "industry": "SaaS",
                "budget_signals": "mentioned Q1 budget",
                "timeline": "next month",
                "use_case": "customer support automation"
            },
            "sentiment": "positive",
            "urgency": "high",
            "engagement_quality": "high",
            "competitor_mentions": ["Intercom", "Zendesk"],
            "recommendations": {
                "follow_up_action": "Schedule demo call",
                "talking_points": ["ROI calculator", "implementation timeline"],
                "content_gaps": ["pricing page", "case studies"]
            },
            "reasoning": "High intent signals with clear timeline and budget"
        }
        """
    )

    class Meta:
        db_table = 'lead_scores'
        verbose_name = 'Lead Score'
        verbose_name_plural = 'Lead Scores'
        ordering = ['-total_score', '-created_at']
        indexes = [
            models.Index(fields=['org_id', 'session_date']),
            models.Index(fields=['org_id', 'priority']),
            models.Index(fields=['chatbot', 'session_date']),
            models.Index(fields=['detected_intent']),
            models.Index(fields=['-total_score']),
            models.Index(fields=['session_date', '-total_score']),
        ]

    def __str__(self):
        return f"Lead {self.priority} - Score {self.total_score} - {self.session_date}"


class WeeklyLeadsReport(BaseModel):
    """
    Stored weekly report for dashboard display and email delivery.

    Reports are generated every Monday for the previous week and
    stored for historical reference and dashboard viewing.
    """
    org = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='weekly_leads_reports',
        help_text="Organization this report belongs to"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='weekly_leads_reports',
        help_text="User who receives this report"
    )
    chatbot = models.ForeignKey(
        'chatbot.Chatbot',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='weekly_leads_reports',
        help_text="Specific chatbot for this report (null = all chatbots)"
    )

    # Report period
    week_start = models.DateField(
        db_index=True,
        help_text="Start date of the report week (Monday)"
    )
    week_end = models.DateField(
        help_text="End date of the report week (Sunday)"
    )

    # Summary metrics
    total_sessions = models.IntegerField(
        default=0,
        help_text="Total chat sessions during the period"
    )
    total_leads = models.IntegerField(
        default=0,
        help_text="Total leads identified (all priorities)"
    )
    hot_leads = models.IntegerField(
        default=0,
        help_text="Number of hot (high priority) leads"
    )
    warm_leads = models.IntegerField(
        default=0,
        help_text="Number of warm (medium priority) leads"
    )
    cold_leads = models.IntegerField(
        default=0,
        help_text="Number of cold (low priority) leads"
    )

    # Comparison with previous period
    leads_change_percent = models.FloatField(
        default=0,
        help_text="Percentage change in leads vs previous week"
    )
    sessions_change_percent = models.FloatField(
        default=0,
        help_text="Percentage change in sessions vs previous week"
    )

    # Detailed report data (JSON for flexibility)
    report_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        Detailed report data structure:
        {
            "top_leads": [{id, priority, intent, score, questions, geo, device, date}],
            "intent_breakdown": {"pricing": 10, "demo": 5, ...},
            "geo_distribution": {"US": 50, "UK": 20, ...},
            "device_breakdown": {"desktop": 60, "mobile": 35, "tablet": 5},
            "daily_trend": [{"date": "2025-01-13", "count": 10}, ...],
            "top_questions": ["How much does it cost?", ...],
            "peak_hours": {"9": 15, "10": 20, ...},
            "avg_session_duration": 180,
            "avg_messages_per_session": 5.2,
            "feedback_summary": {"positive": 20, "negative": 5, "none": 75}
        }
        """
    )

    # Delivery status
    email_sent = models.BooleanField(
        default=False,
        help_text="Whether the email report has been sent"
    )
    email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when email was sent"
    )
    email_error = models.TextField(
        blank=True,
        default='',
        help_text="Error message if email sending failed"
    )

    class Meta:
        db_table = 'weekly_leads_reports'
        verbose_name = 'Weekly Leads Report'
        verbose_name_plural = 'Weekly Leads Reports'
        ordering = ['-week_start']
        constraints = [
            models.UniqueConstraint(
                fields=['org', 'user', 'chatbot', 'week_start'],
                name='unique_weekly_report_per_user_chatbot'
            ),
        ]
        indexes = [
            models.Index(fields=['org', 'week_start']),
            models.Index(fields=['user', 'week_start']),
            models.Index(fields=['email_sent']),
        ]

    def __str__(self):
        chatbot_name = self.chatbot.name if self.chatbot else "All Chatbots"
        return f"Report {self.week_start} - {chatbot_name} - {self.user.email}"


class ReportPreferences(BaseModel):
    """
    User preferences for weekly leads reports.

    Controls email delivery schedule and report content filtering.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='report_preferences',
        help_text="User these preferences belong to"
    )
    org = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='report_preferences',
        help_text="Organization context for these preferences"
    )

    # Email preferences
    weekly_report_enabled = models.BooleanField(
        default=True,
        help_text="Whether to send weekly email reports"
    )
    report_day = models.IntegerField(
        default=0,
        choices=[
            (0, 'Monday'),
            (1, 'Tuesday'),
            (2, 'Wednesday'),
            (3, 'Thursday'),
            (4, 'Friday'),
            (5, 'Saturday'),
            (6, 'Sunday'),
        ],
        help_text="Day of week to send reports (0=Monday)"
    )
    report_hour = models.IntegerField(
        default=9,
        help_text="Hour of day to send reports (0-23, in user's timezone)"
    )
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        help_text="User's timezone for report scheduling"
    )

    # Content preferences
    include_chatbot_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="List of chatbot IDs to include (empty = all chatbots)"
    )
    min_lead_score = models.IntegerField(
        default=0,
        help_text="Minimum lead score to include in reports"
    )
    include_cold_leads = models.BooleanField(
        default=True,
        help_text="Whether to include cold leads in reports"
    )

    # Notification preferences
    notify_hot_leads_immediately = models.BooleanField(
        default=False,
        help_text="Send immediate notification for hot leads"
    )
    daily_summary_enabled = models.BooleanField(
        default=False,
        help_text="Send daily summary in addition to weekly report"
    )

    class Meta:
        db_table = 'report_preferences'
        verbose_name = 'Report Preferences'
        verbose_name_plural = 'Report Preferences'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'org'],
                name='unique_preferences_per_user_org'
            ),
        ]
        indexes = [
            models.Index(fields=['weekly_report_enabled']),
            models.Index(fields=['report_day', 'report_hour']),
        ]

    def __str__(self):
        status = "enabled" if self.weekly_report_enabled else "disabled"
        return f"Preferences for {self.user.email} - {status}"
