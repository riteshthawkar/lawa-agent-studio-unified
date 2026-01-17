"""
Serializers for analytics API endpoints.
"""

from rest_framework import serializers
from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences


class LeadScoreSerializer(serializers.ModelSerializer):
    """Serializer for LeadScore model."""

    chatbot_name = serializers.CharField(source='chatbot.name', read_only=True)
    session_key = serializers.CharField(source='session.session_key', read_only=True)
    has_llm_insights = serializers.SerializerMethodField()

    class Meta:
        model = LeadScore
        fields = [
            'id',
            'session_id',
            'chatbot_id',
            'chatbot_name',
            'session_key',
            'org_id',
            'engagement_score',
            'intent_score',
            'total_score',
            'priority',
            'detected_intent',
            'key_questions',
            'conversation_summary',
            'source_url',
            'geo_location',
            'device_type',
            'session_date',
            'session_duration_seconds',
            'message_count',
            'had_positive_feedback',
            'had_negative_feedback',
            'llm_insights',
            'has_llm_insights',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_has_llm_insights(self, obj):
        return obj.llm_insights is not None and obj.llm_insights.get('analyzed_by_llm', False)


class LeadScoreListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for lead score lists."""

    chatbot_name = serializers.CharField(source='chatbot.name', read_only=True)
    has_llm_insights = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    sentiment = serializers.SerializerMethodField()
    urgency = serializers.SerializerMethodField()

    class Meta:
        model = LeadScore
        fields = [
            'id',
            'priority',
            'total_score',
            'detected_intent',
            'key_questions',
            'conversation_summary',
            'geo_location',
            'device_type',
            'session_date',
            'session_duration_seconds',
            'message_count',
            'chatbot_name',
            'had_positive_feedback',
            'had_negative_feedback',
            'has_llm_insights',
            'company_name',
            'sentiment',
            'urgency',
        ]
        read_only_fields = fields

    def get_has_llm_insights(self, obj):
        return obj.llm_insights is not None and obj.llm_insights.get('analyzed_by_llm', False)

    def get_company_name(self, obj):
        if obj.llm_insights and obj.llm_insights.get('entities'):
            return obj.llm_insights['entities'].get('company_name')
        return None

    def get_sentiment(self, obj):
        if obj.llm_insights:
            return obj.llm_insights.get('sentiment')
        return None

    def get_urgency(self, obj):
        if obj.llm_insights:
            return obj.llm_insights.get('urgency')
        return None


class LeadsSummarySerializer(serializers.Serializer):
    """Serializer for leads summary response."""

    total = serializers.IntegerField()
    hot = serializers.IntegerField()
    warm = serializers.IntegerField()
    cold = serializers.IntegerField()
    period_days = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class WeeklyLeadsReportSerializer(serializers.ModelSerializer):
    """Serializer for WeeklyLeadsReport model."""

    chatbot_name = serializers.CharField(source='chatbot.name', read_only=True, allow_null=True)
    org_name = serializers.CharField(source='org.name', read_only=True)

    class Meta:
        model = WeeklyLeadsReport
        fields = [
            'id',
            'org_id',
            'org_name',
            'chatbot_id',
            'chatbot_name',
            'week_start',
            'week_end',
            'total_sessions',
            'total_leads',
            'hot_leads',
            'warm_leads',
            'cold_leads',
            'leads_change_percent',
            'sessions_change_percent',
            'report_data',
            'email_sent',
            'email_sent_at',
            'created_at',
        ]
        read_only_fields = fields


class WeeklyReportListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for report list."""

    chatbot_name = serializers.CharField(source='chatbot.name', read_only=True, allow_null=True)

    class Meta:
        model = WeeklyLeadsReport
        fields = [
            'id',
            'week_start',
            'week_end',
            'total_leads',
            'hot_leads',
            'warm_leads',
            'cold_leads',
            'leads_change_percent',
            'chatbot_name',
            'email_sent',
        ]
        read_only_fields = fields


class ReportPreferencesSerializer(serializers.ModelSerializer):
    """Serializer for ReportPreferences model."""

    class Meta:
        model = ReportPreferences
        fields = [
            'id',
            'weekly_report_enabled',
            'report_day',
            'report_hour',
            'timezone',
            'include_chatbot_ids',
            'min_lead_score',
            'include_cold_leads',
            'notify_hot_leads_immediately',
            'daily_summary_enabled',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_report_day(self, value):
        if value < 0 or value > 6:
            raise serializers.ValidationError("Report day must be between 0 (Monday) and 6 (Sunday)")
        return value

    def validate_report_hour(self, value):
        if value < 0 or value > 23:
            raise serializers.ValidationError("Report hour must be between 0 and 23")
        return value

    def validate_min_lead_score(self, value):
        if value < 0:
            raise serializers.ValidationError("Minimum lead score cannot be negative")
        return value


class IntentBreakdownSerializer(serializers.Serializer):
    """Serializer for intent breakdown data."""

    intent = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class DailyTrendSerializer(serializers.Serializer):
    """Serializer for daily trend data."""

    date = serializers.DateField()
    total = serializers.IntegerField()
    hot = serializers.IntegerField()
    warm = serializers.IntegerField()
    cold = serializers.IntegerField()


class LeadsDashboardSerializer(serializers.Serializer):
    """Serializer for leads dashboard response."""

    summary = LeadsSummarySerializer()
    leads = LeadScoreListSerializer(many=True)
    intent_breakdown = serializers.ListField(child=serializers.DictField())
    daily_trend = serializers.ListField(child=serializers.DictField())
    geo_distribution = serializers.DictField()
    device_breakdown = serializers.DictField()


class GenerateReportSerializer(serializers.Serializer):
    """Serializer for manual report generation request."""

    chatbot_id = serializers.UUIDField(required=False, allow_null=True)
    week_start = serializers.DateField(required=False, allow_null=True)

    def validate_week_start(self, value):
        if value:
            # Ensure it's a Monday
            if value.weekday() != 0:
                raise serializers.ValidationError("week_start must be a Monday")
        return value
