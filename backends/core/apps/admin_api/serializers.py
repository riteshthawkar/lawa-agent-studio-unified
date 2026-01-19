from rest_framework import serializers
from apps.auth.models import User
from apps.organizations.models import Organization, Membership
from apps.usage.models import Subscription, Quota
from apps.indexing.models import IndexingJob
from apps.chatbot.models import Chatbot
from apps.sites.models import Site
from apps.admin_api.models import AdminAuditLog, LoginHistory

class UserListSerializer(serializers.ModelSerializer):
    """Serializer for user list table"""
    organization_name = serializers.SerializerMethodField()
    tier = serializers.SerializerMethodField()
    is_email_verified = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'name', 'status', 'is_active', 'is_email_verified',
            'created_at', 'last_login', 'organization_name', 'tier'
        ]

    def get_organization_name(self, obj):
        membership = obj.memberships.first()
        if membership:
            return membership.organization.name
        return None

    def get_tier(self, obj):
        membership = obj.memberships.first()
        if membership and hasattr(membership.organization, 'subscription'):
            return membership.organization.subscription.plan
        return 'basic'  # basic is the free tier


class UserDetailSerializer(serializers.ModelSerializer):
    """Detailed user view with all related data"""
    organizations = serializers.SerializerMethodField()
    sites_count = serializers.SerializerMethodField()
    chatbots_count = serializers.SerializerMethodField()
    jobs_count = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'name', 'status', 'is_active', 'is_staff',
            'is_email_verified', 'created_at', 'updated_at', 'last_login',
            'organizations', 'sites_count', 'chatbots_count', 'jobs_count'
        ]
        
    def get_organizations(self, obj):
        orgs = []
        for membership in obj.memberships.select_related('organization').all():
            org = membership.organization
            org_data = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "role": membership.role,
                "plan_tier": org.plan_tier,
                "status": org.status,
            }
            # Add subscription info if available
            if hasattr(org, 'subscription'):
                sub = org.subscription
                org_data['subscription'] = {
                    'plan': sub.plan,
                    'status': sub.status,
                    'features_override': sub.features_override,
                }
            orgs.append(org_data)
        return orgs
    
    def get_sites_count(self, obj):
        org_ids = obj.memberships.values_list('organization_id', flat=True)
        return Site.objects.filter(org_id__in=org_ids).count()
    
    def get_chatbots_count(self, obj):
        org_ids = obj.memberships.values_list('organization_id', flat=True)
        site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
        return Chatbot.objects.filter(site_id__in=site_ids).count()
    
    def get_jobs_count(self, obj):
        org_ids = obj.memberships.values_list('organization_id', flat=True)
        site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
        return IndexingJob.objects.filter(site_id__in=site_ids).count()


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for admin to update user fields (limited)"""
    class Meta:
        model = User
        fields = ['status', 'is_active', 'is_email_verified', 'is_staff']


class OrganizationListSerializer(serializers.ModelSerializer):
    """Organization list with subscription info"""
    owner_email = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    sites_count = serializers.SerializerMethodField()
    chatbots_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'slug', 'status', 'plan_tier', 'created_at',
            'owner_email', 'plan', 'subscription_status', 'sites_count', 'chatbots_count'
        ]

    def get_owner_email(self, obj):
        owner = obj.memberships.filter(role='owner').select_related('user').first()
        return owner.user.email if owner else None
    
    def get_plan(self, obj):
        if hasattr(obj, 'subscription'):
            return obj.subscription.plan
        return obj.plan_tier
    
    def get_subscription_status(self, obj):
        if hasattr(obj, 'subscription'):
            return obj.subscription.status
        return 'none'
    
    def get_sites_count(self, obj):
        return Site.objects.filter(org_id=obj.id).count()
    
    def get_chatbots_count(self, obj):
        site_ids = Site.objects.filter(org_id=obj.id).values_list('id', flat=True)
        return Chatbot.objects.filter(site_id__in=site_ids).count()


class OrganizationDetailSerializer(serializers.ModelSerializer):
    """Detailed organization view with limits and usage"""
    owner_email = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField()
    limits = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()
    
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'slug', 'status', 'plan_tier', 'created_at', 'updated_at',
            'owner_email', 'members', 'subscription', 'limits', 'usage'
        ]
    
    def get_owner_email(self, obj):
        owner = obj.memberships.filter(role='owner').select_related('user').first()
        return owner.user.email if owner else None
    
    def get_members(self, obj):
        return [
            {
                'user_id': str(m.user_id),
                'email': m.user.email,
                'name': m.user.name,
                'role': m.role,
                'is_active': m.is_active
            }
            for m in obj.memberships.select_related('user').all()
        ]
    
    def get_subscription(self, obj):
        if hasattr(obj, 'subscription'):
            sub = obj.subscription
            return {
                'plan': sub.plan,
                'status': sub.status,
                'trial_ends_at': sub.trial_ends_at,
                'features_override': sub.features_override,
                'stripe_customer_id': sub.stripe_customer_id,
            }
        return None
    
    def get_limits(self, obj):
        from apps.usage.services import QuotaService
        return QuotaService.get_org_limits(obj.id)
    
    def get_usage(self, obj):
        from apps.usage.services import QuotaService
        return QuotaService.get_org_usage(obj.id)


class QuotaUpdateSerializer(serializers.Serializer):
    """Serializer for updating organization quotas with confirmation"""
    limits = serializers.DictField(required=True)
    confirm = serializers.BooleanField(required=True, help_text="Must be true to apply changes")
    
    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError("You must confirm the changes.")
        return value


class AdminActionSerializer(serializers.Serializer):
    """Serializer for admin actions like suspend, reset password"""
    action = serializers.ChoiceField(choices=[
        'suspend', 'activate', 'reset_password', 'send_email',
        'verify_email', 'unverify_email', 'delete'
    ])
    payload = serializers.JSONField(required=False)


class IndexingJobSerializer(serializers.ModelSerializer):
    """Serializer for indexing jobs in admin view"""
    site_domain = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    trigger_type = serializers.SerializerMethodField()
    org_name = serializers.SerializerMethodField()

    class Meta:
        model = IndexingJob
        fields = [
            'id', 'site_id', 'site_domain', 'org_id', 'org_name', 'status', 'trigger_type',
            'urls_collected', 'urls_processed', 'documents_indexed',
            'started_at', 'completed_at', 'duration_seconds',
            'error_message', 'created_at', 'url', 'max_pages'
        ]

    def get_site_domain(self, obj):
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.domain
        except Site.DoesNotExist:
            return None

    def get_org_name(self, obj):
        if not obj.org_id:
            return None
        try:
            org = Organization.objects.get(id=obj.org_id)
            return org.name
        except Organization.DoesNotExist:
            return None

    def get_trigger_type(self, obj):
        # For now, we infer from context - could be stored in metadata later
        return 'manual'

    def get_duration_seconds(self, obj):
        return obj.duration


class ChatbotAdminSerializer(serializers.ModelSerializer):
    """Serializer for chatbots in admin view"""
    site_domain = serializers.SerializerMethodField()
    
    class Meta:
        model = Chatbot
        fields = [
            'id', 'name', 'site_id', 'site_domain', 'status',
            'api_key', 'created_at', 'updated_at'
        ]
    
    def get_site_domain(self, obj):
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.domain
        except Site.DoesNotExist:
            return None


class SiteAdminSerializer(serializers.ModelSerializer):
    """Serializer for sites in admin view"""
    chatbots_count = serializers.SerializerMethodField()
    jobs_count = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = [
            'id', 'name', 'domain', 'status', 'org_id', 'organization_name',
            'indexed_pages_count', 'total_documents', 'last_indexed_at',
            'created_at', 'chatbots_count', 'jobs_count'
        ]

    def get_organization_name(self, obj):
        if not obj.org_id:
            return None
        try:
            org = Organization.objects.get(id=obj.org_id)
            return org.name
        except Organization.DoesNotExist:
            return None

    def get_chatbots_count(self, obj):
        return Chatbot.objects.filter(site_id=obj.id).count()

    def get_jobs_count(self, obj):
        return IndexingJob.objects.filter(site_id=obj.id).count()


# =====================
# Audit & Security Serializers
# =====================

class AdminAuditLogSerializer(serializers.ModelSerializer):
    """Serializer for admin audit logs"""
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    
    class Meta:
        model = AdminAuditLog
        fields = [
            'id', 'admin_email', 'action', 'action_display',
            'target_type', 'target_id', 'target_label',
            'details', 'ip_address', 'created_at'
        ]
        read_only_fields = fields


class LoginHistorySerializer(serializers.ModelSerializer):
    """Serializer for user login history"""
    user_email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = LoginHistory
        fields = [
            'id', 'user_email', 'success', 'ip_address',
            'user_agent', 'country', 'city', 'created_at'
        ]
        read_only_fields = fields


class BulkActionSerializer(serializers.Serializer):
    """Serializer for bulk user actions"""
    user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100
    )
    action = serializers.ChoiceField(choices=['suspend', 'activate', 'delete'])


# =====================
# Waitlist/Upgrade Interest Serializers
# =====================

class UpgradeInterestAdminSerializer(serializers.ModelSerializer):
    """Admin serializer for upgrade interest with full details"""
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    organization_plan = serializers.CharField(source='organization.plan_tier', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.name', read_only=True)

    class Meta:
        from apps.usage.models import UpgradeInterest
        model = UpgradeInterest
        fields = [
            'id', 'organization', 'organization_name', 'organization_plan',
            'user', 'user_email', 'user_name',
            'interested_plan', 'email', 'company_name', 'message',
            'source', 'status', 'metadata',
            'contacted_at', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UpgradeInterestUpdateSerializer(serializers.Serializer):
    """Serializer for updating waitlist entry status"""
    status = serializers.ChoiceField(
        choices=['pending', 'contacted', 'converted', 'declined'],
        required=False
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    def validate(self, data):
        if not data:
            raise serializers.ValidationError("At least one field must be provided")
        return data


# =====================
# Feedback & Help Center Serializers
# =====================

class FeedbackListSerializer(serializers.ModelSerializer):
    """Serializer for feedback list in admin view"""
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)
    user_name = serializers.CharField(source='user.name', read_only=True, allow_null=True)
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        from apps.support.models import Feedback
        model = Feedback
        fields = [
            'id', 'user', 'user_email', 'user_name', 'email', 'org_id',
            'feedback_type', 'feedback_type_display',
            'subject', 'message',
            'status', 'status_display',
            'priority', 'priority_display',
            'created_at', 'resolved_at'
        ]


class FeedbackDetailSerializer(serializers.ModelSerializer):
    """Detailed feedback view for admin"""
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)
    user_name = serializers.CharField(source='user.name', read_only=True, allow_null=True)
    resolved_by_email = serializers.CharField(source='resolved_by.email', read_only=True, allow_null=True)
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        from apps.support.models import Feedback
        model = Feedback
        fields = [
            'id', 'user', 'user_email', 'user_name', 'email', 'org_id',
            'feedback_type', 'feedback_type_display',
            'subject', 'message',
            'page_url', 'user_agent', 'screen_resolution',
            'steps_to_reproduce', 'expected_behavior', 'actual_behavior',
            'status', 'status_display',
            'priority', 'priority_display',
            'admin_notes', 'resolved_at', 'resolved_by', 'resolved_by_email',
            'created_at', 'updated_at'
        ]


class FeedbackUpdateSerializer(serializers.Serializer):
    """Serializer for updating feedback status and notes"""
    status = serializers.ChoiceField(
        choices=['pending', 'in_review', 'acknowledged', 'in_progress', 'resolved', 'closed'],
        required=False
    )
    priority = serializers.ChoiceField(
        choices=['low', 'medium', 'high', 'critical'],
        required=False
    )
    admin_notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)

    def validate(self, data):
        if not data:
            raise serializers.ValidationError("At least one field must be provided")
        return data


class FAQCategorySerializer(serializers.ModelSerializer):
    """Serializer for FAQ categories"""
    faqs_count = serializers.SerializerMethodField()
    articles_count = serializers.SerializerMethodField()

    class Meta:
        from apps.support.models import FAQCategory
        model = FAQCategory
        fields = [
            'id', 'name', 'slug', 'description', 'icon',
            'order', 'is_active', 'faqs_count', 'articles_count',
            'created_at', 'updated_at'
        ]

    def get_faqs_count(self, obj):
        return obj.faqs.count() if hasattr(obj, 'faqs') else 0

    def get_articles_count(self, obj):
        return obj.articles.count() if hasattr(obj, 'articles') else 0


class FAQCategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating FAQ categories"""
    class Meta:
        from apps.support.models import FAQCategory
        model = FAQCategory
        fields = ['name', 'slug', 'description', 'icon', 'order', 'is_active']


class FAQSerializer(serializers.ModelSerializer):
    """Serializer for FAQs"""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    helpfulness_ratio = serializers.SerializerMethodField()

    class Meta:
        from apps.support.models import FAQ
        model = FAQ
        fields = [
            'id', 'category', 'category_name',
            'question', 'answer',
            'order', 'is_active', 'is_featured',
            'helpful_count', 'not_helpful_count', 'view_count',
            'helpfulness_ratio', 'tags',
            'created_at', 'updated_at'
        ]

    def get_helpfulness_ratio(self, obj):
        total = obj.helpful_count + obj.not_helpful_count
        if total == 0:
            return None
        return round(obj.helpful_count / total * 100, 1)


class FAQCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating FAQs"""
    class Meta:
        from apps.support.models import FAQ
        model = FAQ
        fields = [
            'category', 'question', 'answer',
            'order', 'is_active', 'is_featured', 'tags'
        ]


class HelpArticleListSerializer(serializers.ModelSerializer):
    """Serializer for help article list"""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    article_type_display = serializers.CharField(source='get_article_type_display', read_only=True)
    helpfulness_ratio = serializers.SerializerMethodField()

    class Meta:
        from apps.support.models import HelpArticle
        model = HelpArticle
        fields = [
            'id', 'title', 'slug', 'article_type', 'article_type_display',
            'summary', 'category', 'category_name',
            'order', 'is_active', 'is_featured',
            'view_count', 'helpful_count', 'not_helpful_count',
            'helpfulness_ratio', 'tags',
            'created_at', 'updated_at'
        ]

    def get_helpfulness_ratio(self, obj):
        total = obj.helpful_count + obj.not_helpful_count
        if total == 0:
            return None
        return round(obj.helpful_count / total * 100, 1)


class HelpArticleDetailSerializer(serializers.ModelSerializer):
    """Detailed help article serializer"""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    article_type_display = serializers.CharField(source='get_article_type_display', read_only=True)
    related_articles_data = serializers.SerializerMethodField()
    helpfulness_ratio = serializers.SerializerMethodField()

    class Meta:
        from apps.support.models import HelpArticle
        model = HelpArticle
        fields = [
            'id', 'title', 'slug', 'article_type', 'article_type_display',
            'summary', 'content', 'icon',
            'category', 'category_name',
            'order', 'is_active', 'is_featured',
            'view_count', 'helpful_count', 'not_helpful_count',
            'helpfulness_ratio', 'related_articles', 'related_articles_data',
            'tags', 'created_at', 'updated_at'
        ]

    def get_related_articles_data(self, obj):
        return [
            {'id': str(a.id), 'title': a.title, 'slug': a.slug}
            for a in obj.related_articles.all()[:5]
        ]

    def get_helpfulness_ratio(self, obj):
        total = obj.helpful_count + obj.not_helpful_count
        if total == 0:
            return None
        return round(obj.helpful_count / total * 100, 1)


class HelpArticleCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating help articles"""
    class Meta:
        from apps.support.models import HelpArticle
        model = HelpArticle
        fields = [
            'title', 'slug', 'article_type', 'summary', 'content', 'icon',
            'category', 'order', 'is_active', 'is_featured',
            'related_articles', 'tags'
        ]


# =====================
# Admin Authentication Serializers
# =====================

class AdminLoginSerializer(serializers.Serializer):
    """
    Serializer for admin login - validates credentials AND superuser status
    before issuing tokens (security-critical).
    """
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        from django.contrib.auth import authenticate

        email = attrs.get('email')
        password = attrs.get('password')

        if not email or not password:
            raise serializers.ValidationError('Email and password are required')

        # Authenticate user
        user = authenticate(username=email, password=password)

        if not user:
            raise serializers.ValidationError('Invalid email or password')

        if not user.is_active:
            raise serializers.ValidationError('Account is disabled')

        # CRITICAL: Check admin privileges BEFORE returning user
        if not user.is_superuser and not user.is_staff:
            raise serializers.ValidationError('Access denied. Administrator privileges required.')

        attrs['user'] = user
        return attrs


class AdminUserSerializer(serializers.ModelSerializer):
    """Serializer for admin user data in login response"""
    has_2fa = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'name', 'username',
            'is_staff', 'is_superuser', 'is_active',
            'created_at', 'last_login', 'has_2fa'
        ]
        read_only_fields = fields

    def get_has_2fa(self, obj):
        from apps.admin_api.models import Admin2FA
        return Admin2FA.is_2fa_enabled(obj)


# ===========================================
# 2FA Serializers
# ===========================================

class TwoFactorSetupSerializer(serializers.Serializer):
    """Response serializer for 2FA setup initiation"""
    secret = serializers.CharField(read_only=True)
    qr_code = serializers.CharField(read_only=True, help_text="Base64 encoded QR code image")
    provisioning_uri = serializers.CharField(read_only=True)


class TwoFactorVerifySerializer(serializers.Serializer):
    """Serializer for verifying 2FA code"""
    code = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text="6-digit TOTP code from authenticator app"
    )

    def validate_code(self, value):
        # Only digits allowed
        if not value.isdigit():
            raise serializers.ValidationError("Code must contain only digits")
        return value


class TwoFactorDisableSerializer(serializers.Serializer):
    """Serializer for disabling 2FA"""
    code = serializers.CharField(
        min_length=6,
        max_length=8,
        help_text="Current TOTP code or backup code"
    )
    password = serializers.CharField(
        write_only=True,
        help_text="Current password for confirmation"
    )


class TwoFactorStatusSerializer(serializers.Serializer):
    """Serializer for 2FA status response"""
    is_enabled = serializers.BooleanField()
    enabled_at = serializers.DateTimeField(allow_null=True)
    last_used_at = serializers.DateTimeField(allow_null=True)
    backup_codes_remaining = serializers.IntegerField()


class TwoFactorLoginSerializer(serializers.Serializer):
    """Serializer for 2FA verification during login"""
    temp_token = serializers.CharField(
        help_text="Temporary token from initial login"
    )
    code = serializers.CharField(
        min_length=6,
        max_length=8,
        help_text="6-digit TOTP code or 8-character backup code"
    )


class BackupCodesResponseSerializer(serializers.Serializer):
    """Response serializer for backup codes generation"""
    backup_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="One-time backup codes (store securely, shown only once)"
    )
    message = serializers.CharField()


# ===========================================
# Alerting System Serializers
# ===========================================

class AlertRuleSerializer(serializers.ModelSerializer):
    """Serializer for alert rules"""
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    channel_display = serializers.CharField(source='get_notification_channel_display', read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, allow_null=True)
    notifications_count = serializers.SerializerMethodField()
    last_triggered = serializers.SerializerMethodField()

    class Meta:
        from apps.admin_api.models import AlertRule
        model = AlertRule
        fields = [
            'id', 'name', 'description',
            'alert_type', 'alert_type_display',
            'severity', 'severity_display',
            'conditions',
            'notification_channel', 'channel_display', 'notification_target',
            'cooldown_minutes', 'is_enabled',
            'created_by', 'created_by_email',
            'notifications_count', 'last_triggered',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_notifications_count(self, obj):
        return obj.notifications.count()

    def get_last_triggered(self, obj):
        last = obj.notifications.order_by('-sent_at').first()
        return last.sent_at if last else None


class AlertRuleCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating alert rules"""
    class Meta:
        from apps.admin_api.models import AlertRule
        model = AlertRule
        fields = [
            'name', 'description', 'alert_type', 'severity',
            'conditions', 'notification_channel', 'notification_target',
            'cooldown_minutes', 'is_enabled'
        ]

    def validate_conditions(self, value):
        alert_type = self.initial_data.get('alert_type')

        if alert_type == 'failed_logins':
            if 'threshold' not in value:
                value['threshold'] = 5
            if 'time_window_minutes' not in value:
                value['time_window_minutes'] = 10

        elif alert_type == 'job_failures':
            if 'threshold' not in value:
                value['threshold'] = 3
            if 'time_window_hours' not in value:
                value['time_window_hours'] = 1

        return value

    def validate_notification_target(self, value):
        channel = self.initial_data.get('notification_channel')

        if channel == 'email':
            if '@' not in value:
                raise serializers.ValidationError("Invalid email address")

        elif channel in ['webhook', 'slack']:
            if not value.startswith('http'):
                raise serializers.ValidationError("Invalid URL")

        return value


class AlertNotificationSerializer(serializers.ModelSerializer):
    """Serializer for alert notifications"""
    rule_name = serializers.CharField(source='rule.name', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)

    class Meta:
        from apps.admin_api.models import AlertNotification
        model = AlertNotification
        fields = [
            'id', 'rule', 'rule_name',
            'title', 'message', 'severity', 'severity_display',
            'sent_at', 'delivered', 'delivery_error',
            'context'
        ]
        read_only_fields = fields


class SystemAlertSerializer(serializers.ModelSerializer):
    """Serializer for system alerts displayed in dashboard"""
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    acknowledged_by_email = serializers.CharField(
        source='acknowledged_by.email', read_only=True, allow_null=True
    )

    class Meta:
        from apps.admin_api.models import SystemAlert
        model = SystemAlert
        fields = [
            'id', 'title', 'message', 'level', 'level_display',
            'related_type', 'related_id',
            'is_active', 'is_acknowledged',
            'acknowledged_by', 'acknowledged_by_email', 'acknowledged_at',
            'auto_resolve', 'resolved_at',
            'created_at', 'expires_at'
        ]
        read_only_fields = fields


class SystemAlertCreateSerializer(serializers.Serializer):
    """Serializer for creating manual system alerts"""
    title = serializers.CharField(max_length=255)
    message = serializers.CharField()
    level = serializers.ChoiceField(
        choices=['info', 'warning', 'error', 'critical'],
        default='warning'
    )
    related_type = serializers.CharField(max_length=50, required=False, default='')
    related_id = serializers.CharField(max_length=100, required=False, default='')
    expires_hours = serializers.IntegerField(min_value=1, max_value=720, default=24)


class SystemAlertAcknowledgeSerializer(serializers.Serializer):
    """Serializer for acknowledging system alerts"""
    pass  # No input needed, user is taken from request


class AlertStatsSerializer(serializers.Serializer):
    """Serializer for alert statistics"""
    active_alerts = serializers.IntegerField()
    critical_alerts = serializers.IntegerField()
    warning_alerts = serializers.IntegerField()
    alerts_today = serializers.IntegerField()
    alerts_this_week = serializers.IntegerField()
    enabled_rules = serializers.IntegerField()
    total_rules = serializers.IntegerField()


# =====================
# Announcement Serializers
# =====================

class AnnouncementListSerializer(serializers.Serializer):
    """Serializer for announcement list"""
    id = serializers.UUIDField()
    title = serializers.CharField()
    message = serializers.CharField()
    announcement_type = serializers.CharField()
    style = serializers.CharField()
    is_active = serializers.BooleanField()
    is_dismissible = serializers.BooleanField()
    starts_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    view_count = serializers.IntegerField()
    dismiss_count = serializers.IntegerField()


class AnnouncementDetailSerializer(serializers.Serializer):
    """Serializer for announcement detail"""
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField()
    message = serializers.CharField()
    announcement_type = serializers.ChoiceField(choices=['banner', 'modal', 'toast'])
    style = serializers.ChoiceField(choices=['info', 'warning', 'success', 'error'])
    link_url = serializers.URLField(required=False, allow_blank=True)
    link_text = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_dismissible = serializers.BooleanField(default=True)
    show_to_all = serializers.BooleanField(default=True)
    target_tiers = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    is_active = serializers.BooleanField(default=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    view_count = serializers.IntegerField(read_only=True)
    dismiss_count = serializers.IntegerField(read_only=True)
    created_by_email = serializers.SerializerMethodField()

    def get_created_by_email(self, obj):
        return obj.created_by.email if obj.created_by else None

    def get_style(self, obj):
        return obj.get_style_display()


class AnnouncementCreateSerializer(serializers.Serializer):
    """Serializer for creating announcements"""
    title = serializers.CharField(max_length=255)
    message = serializers.CharField()
    announcement_type = serializers.ChoiceField(
        choices=['banner', 'modal', 'toast'],
        default='banner'
    )
    style = serializers.ChoiceField(
        choices=['info', 'warning', 'success', 'error'],
        default='info'
    )
    link_url = serializers.URLField(required=False, allow_blank=True)
    link_text = serializers.CharField(max_length=50, required=False, allow_blank=True)
    is_dismissible = serializers.BooleanField(default=True)
    show_to_all = serializers.BooleanField(default=True)
    target_tiers = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True
    )
    is_active = serializers.BooleanField(default=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


# =====================
# Feature Flag Serializers
# =====================

class FeatureFlagSerializer(serializers.ModelSerializer):
    """Serializer for feature flags"""
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        from apps.admin_api.models import FeatureFlag
        model = FeatureFlag
        fields = [
            'id', 'key', 'name', 'description', 'is_enabled', 
            'rollout_strategy', 'target_tiers', 'rollout_percentage', 
            'target_user_ids', 'environment', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def validate_key(self, value):
        from apps.admin_api.models import FeatureFlag
        # Check uniqueness but exclude current instance if updating
        qs = FeatureFlag.objects.filter(key=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError("A feature flag with this key already exists.")
        return value
