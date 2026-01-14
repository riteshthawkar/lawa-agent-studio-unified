from rest_framework import serializers
from .models import UsageEvent, Quota, UpgradeInterest


class UsageEventSerializer(serializers.ModelSerializer):
    """Serializer for UsageEvent model"""

    class Meta:
        model = UsageEvent
        fields = (
            'id', 'org_id', 'site_id', 'chatbot_id', 'session_id',
            'type', 'units', 'cost_cents', 'meta', 'occurred_at'
        )
        read_only_fields = ('id', 'occurred_at')


class QuotaSerializer(serializers.ModelSerializer):
    """Serializer for Quota model"""

    class Meta:
        model = Quota
        fields = (
            'id', 'org_id', 'period_start', 'period_end',
            'limits', 'usage', 'created_at'
        )
        read_only_fields = ('id', 'created_at')


class UpgradeInterestCreateSerializer(serializers.Serializer):
    """Serializer for creating upgrade interest / joining waitlist"""
    interested_plan = serializers.ChoiceField(
        choices=['premium', 'enterprise'],
        help_text="Plan the user is interested in"
    )
    email = serializers.EmailField(
        help_text="Contact email for notifications"
    )
    source = serializers.ChoiceField(
        choices=[
            'billing_page',
            'upgrade_prompt',
            'limit_reached',
            'feature_locked',
            'usage_page',
            'other'
        ],
        default='billing_page',
        help_text="Where the interest was expressed"
    )
    company_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Company name (required for enterprise)"
    )
    message = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        help_text="Optional message or requirements"
    )

    def validate(self, data):
        """Validate enterprise requires company name"""
        if data.get('interested_plan') == 'enterprise':
            if not data.get('company_name', '').strip():
                raise serializers.ValidationError({
                    'company_name': 'Company name is required for enterprise inquiries'
                })
        return data


class UpgradeInterestSerializer(serializers.ModelSerializer):
    """Serializer for reading upgrade interest records"""

    class Meta:
        model = UpgradeInterest
        fields = (
            'id', 'interested_plan', 'email', 'source',
            'company_name', 'message', 'status', 'created_at'
        )
        read_only_fields = ('id', 'status', 'created_at')


class UsageSummarySerializer(serializers.Serializer):
    """Serializer for usage summary response"""
    sites = serializers.DictField()
    chatbots = serializers.DictField()
    daily_conversations = serializers.DictField()
    total_conversations = serializers.DictField()
