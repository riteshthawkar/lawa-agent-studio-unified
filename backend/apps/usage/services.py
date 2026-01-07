"""
Quota enforcement service for strict limit checking.

This service provides methods to check and enforce organization limits
before resource creation and usage. Limits are applied IMMEDIATELY
and STRICTLY - no grace periods.

Tier Structure:
- basic: Free tier for all users
- premium: Paid tier with enhanced features
- enterprise: Custom tier (unlimited)
"""
import logging
from django.utils import timezone
from django.db.models import Count
from apps.usage.models import Quota, Subscription, UsageEvent
from apps.usage.tier_config import TIER_FEATURES, get_tier_limits, is_unlimited
from apps.organizations.models import Organization
from apps.sites.models import Site
from apps.chatbot.models import Chatbot

logger = logging.getLogger(__name__)


class UsageTracker:
    """Utility class to track usage events across the platform."""
    
    @staticmethod
    def track_event(org_id, event_type, units=1, site_id=None, meta=None):
        """
        Track a usage event.
        
        Args:
            org_id: Organization UUID
            event_type: Type of event (e.g., 'index_write', 'chat', 'query')
            units: Number of units consumed
            site_id: Optional site UUID
            meta: Optional metadata dictionary
        """
        if not org_id:
            logger.debug(f"Skipping usage tracking - no org_id provided for event {event_type}")
            return None
            
        try:
            event = UsageEvent.objects.create(
                org_id=org_id,
                type=event_type,
                units=units,
                cost_cents=0,  # Cost calculation can be added later
                occurred_at=timezone.now(),
                meta=meta or {}
            )
            logger.debug(f"Tracked usage event: {event_type} x{units} for org {org_id}")
            return event
        except Exception as e:
            logger.error(f"Failed to track usage event: {e}")
            return None


# Default limits per plan tier - matches tier_config.py
TIER_LIMITS = {
    'basic': {
        'max_sites': 1,
        'max_chatbots': 1,
        'max_pages_per_site': 50,
        'daily_conversations': 100,
        'max_conversations': 5000,
        'analytics_retention_days': 7,
    },
    'premium': {
        'max_sites': 10,
        'max_chatbots': 25,
        'max_pages_per_site': 500,
        'daily_conversations': 1000,
        'max_conversations': None,  # Unlimited
        'analytics_retention_days': 90,
    },
    'enterprise': {
        'max_sites': None,  # Unlimited
        'max_chatbots': None,  # Unlimited
        'max_pages_per_site': None,  # Unlimited
        'daily_conversations': None,  # Unlimited
        'max_conversations': None,  # Unlimited
        'analytics_retention_days': 365,
    },
}


class QuotaLimitExceeded(Exception):
    """Exception raised when a quota limit is exceeded."""
    def __init__(self, message, limit_type, current_value, max_value):
        super().__init__(message)
        self.message = message
        self.limit_type = limit_type
        self.current_value = current_value
        self.max_value = max_value


class QuotaService:
    """Service for checking and enforcing organization quotas."""

    @staticmethod
    def get_org_limits(org_id) -> dict:
        """
        Get effective limits for an organization.
        Priority: Custom Quota > Subscription Override > Tier Default
        """
        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            logger.warning(f"Organization {org_id} not found, using basic tier limits")
            return TIER_LIMITS['basic'].copy()

        # Start with tier defaults based on plan_tier
        tier = org.plan_tier or 'basic'
        limits = TIER_LIMITS.get(tier, TIER_LIMITS['basic']).copy()

        # Check for subscription overrides
        try:
            subscription = Subscription.objects.get(organization=org)
            if subscription.features_override:
                limits.update(subscription.features_override)
        except Subscription.DoesNotExist:
            pass

        # Check for custom quota overrides (highest priority)
        now = timezone.now()
        try:
            quota = Quota.objects.filter(
                org_id=org_id,
                period_start__lte=now,
                period_end__gte=now
            ).order_by('-created_at').first()
            if quota and quota.limits:
                limits.update(quota.limits)
        except Exception as e:
            logger.error(f"Error fetching quota for org {org_id}: {e}")

        return limits

    @staticmethod
    def get_org_usage(org_id) -> dict:
        """Get current usage counts for an organization."""
        usage = {}

        # Count sites
        usage['sites_count'] = Site.objects.filter(org_id=org_id).count()

        # Count chatbots
        usage['chatbots_count'] = Chatbot.objects.filter(
            site_id__in=Site.objects.filter(org_id=org_id).values_list('id', flat=True)
        ).count()

        # Count conversations today
        start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        usage['daily_conversations'] = UsageEvent.objects.filter(
            org_id=org_id,
            type='chat',
            occurred_at__gte=start_of_day
        ).count()

        # Count total conversations (all time)
        usage['total_conversations'] = UsageEvent.objects.filter(
            org_id=org_id,
            type='chat'
        ).count()

        return usage

    @classmethod
    def check_site_limit(cls, org_id) -> tuple[bool, str]:
        """
        Check if organization can create a new site.
        Returns (allowed, reason_if_not_allowed)
        """
        limits = cls.get_org_limits(org_id)
        max_sites = limits.get('max_sites')

        if max_sites is None:  # Unlimited
            return True, ""

        current_count = Site.objects.filter(org_id=org_id).count()

        if current_count >= max_sites:
            return False, f"Project limit reached ({current_count}/{max_sites}). Upgrade to create more projects."

        return True, ""

    @classmethod
    def enforce_site_limit(cls, org_id):
        """Enforce site limit - raises QuotaLimitExceeded if exceeded."""
        allowed, reason = cls.check_site_limit(org_id)
        if not allowed:
            limits = cls.get_org_limits(org_id)
            raise QuotaLimitExceeded(
                reason,
                'max_sites',
                Site.objects.filter(org_id=org_id).count(),
                limits.get('max_sites')
            )

    @classmethod
    def check_chatbot_limit(cls, org_id) -> tuple[bool, str]:
        """Check if organization can create a new chatbot."""
        limits = cls.get_org_limits(org_id)
        max_chatbots = limits.get('max_chatbots')

        if max_chatbots is None:  # Unlimited
            return True, ""

        # Count chatbots across all org's sites
        site_ids = Site.objects.filter(org_id=org_id).values_list('id', flat=True)
        current_count = Chatbot.objects.filter(site_id__in=site_ids).count()

        if current_count >= max_chatbots:
            return False, f"Chatbot limit reached ({current_count}/{max_chatbots}). Upgrade to create more chatbots."

        return True, ""

    @classmethod
    def enforce_chatbot_limit(cls, org_id):
        """Enforce chatbot limit - raises QuotaLimitExceeded if exceeded."""
        allowed, reason = cls.check_chatbot_limit(org_id)
        if not allowed:
            limits = cls.get_org_limits(org_id)
            site_ids = Site.objects.filter(org_id=org_id).values_list('id', flat=True)
            raise QuotaLimitExceeded(
                reason,
                'max_chatbots',
                Chatbot.objects.filter(site_id__in=site_ids).count(),
                limits.get('max_chatbots')
            )

    @classmethod
    def check_daily_conversation_limit(cls, org_id) -> tuple[bool, str]:
        """Check if organization can have more conversations today."""
        limits = cls.get_org_limits(org_id)
        max_daily = limits.get('daily_conversations')

        if max_daily is None:  # Unlimited
            return True, ""

        start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        current_count = UsageEvent.objects.filter(
            org_id=org_id,
            type='chat',
            occurred_at__gte=start_of_day
        ).count()

        if current_count >= max_daily:
            return False, f"Daily conversation limit reached ({current_count}/{max_daily}). Limit resets at midnight."

        return True, ""

    @classmethod
    def check_total_conversation_limit(cls, org_id) -> tuple[bool, str]:
        """Check if organization has reached total conversation limit."""
        limits = cls.get_org_limits(org_id)
        max_total = limits.get('max_conversations')

        if max_total is None:  # Unlimited
            return True, ""

        current_count = UsageEvent.objects.filter(
            org_id=org_id,
            type='chat'
        ).count()

        if current_count >= max_total:
            return False, f"Total conversation limit reached ({current_count}/{max_total}). Upgrade for unlimited conversations."

        return True, ""

    @classmethod
    def enforce_conversation_limit(cls, org_id):
        """Enforce conversation limits - raises QuotaLimitExceeded if exceeded."""
        # Check daily limit first
        allowed, reason = cls.check_daily_conversation_limit(org_id)
        if not allowed:
            limits = cls.get_org_limits(org_id)
            start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            raise QuotaLimitExceeded(
                reason,
                'daily_conversations',
                UsageEvent.objects.filter(
                    org_id=org_id,
                    type='chat',
                    occurred_at__gte=start_of_day
                ).count(),
                limits.get('daily_conversations')
            )

        # Then check total limit
        allowed, reason = cls.check_total_conversation_limit(org_id)
        if not allowed:
            limits = cls.get_org_limits(org_id)
            raise QuotaLimitExceeded(
                reason,
                'max_conversations',
                UsageEvent.objects.filter(
                    org_id=org_id,
                    type='chat'
                ).count(),
                limits.get('max_conversations')
            )

    @classmethod
    def check_indexing_job_quota(cls, org_id, plan_tier) -> tuple[bool, str]:
        """Check if organization can start a new indexing job."""
        if not org_id:
            # If no org context, we can't enforce quota (or assume individual user quota)
            return True, ""
            
        limits = cls.get_org_limits(org_id)
        
        # Determine strict concurrent job limit
        # Default fallback values if not in limits config
        default_concurrency = 1
        if plan_tier == 'premium':
            default_concurrency = 3
        elif plan_tier == 'enterprise':
            default_concurrency = 10
            
        max_concurrent = limits.get('concurrent_jobs', default_concurrency)
            
        if max_concurrent is None: # Unlimited
             return True, ""

        from apps.indexing.models import IndexingJob
        from apps.sites.models import Site
        
        # Get sites for org
        site_ids = Site.objects.filter(org_id=org_id).values_list('id', flat=True)
        
        # Count active jobs across all sites in the organization
        active_jobs = IndexingJob.objects.filter(
            site_id__in=site_ids, 
            status__in=['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']
        ).count()
        
        if active_jobs >= max_concurrent:
            return False, f"Concurrent indexing job limit reached ({active_jobs}/{max_concurrent}). Please wait for existing jobs to complete."
            
        return True, ""

    @classmethod
    def get_page_limit(cls, org_id) -> int:
        """Get the maximum pages per site for indexing jobs."""
        limits = cls.get_org_limits(org_id)
        max_pages = limits.get('max_pages_per_site')
        return max_pages if max_pages is not None else 10000  # Default high for enterprise

    @classmethod
    def get_usage_summary(cls, org_id) -> dict:
        """Get a summary of usage for display in the dashboard."""
        limits = cls.get_org_limits(org_id)
        usage = cls.get_org_usage(org_id)

        def calc_percentage(used, limit):
            if limit is None:
                return 0
            if limit == 0:
                return 100 if used > 0 else 0
            return min(100, round((used / limit) * 100))

        return {
            'sites': {
                'used': usage['sites_count'],
                'limit': limits.get('max_sites'),
                'percentage': calc_percentage(usage['sites_count'], limits.get('max_sites'))
            },
            'chatbots': {
                'used': usage['chatbots_count'],
                'limit': limits.get('max_chatbots'),
                'percentage': calc_percentage(usage['chatbots_count'], limits.get('max_chatbots'))
            },
            'daily_conversations': {
                'used': usage['daily_conversations'],
                'limit': limits.get('daily_conversations'),
                'percentage': calc_percentage(usage['daily_conversations'], limits.get('daily_conversations'))
            },
            'total_conversations': {
                'used': usage['total_conversations'],
                'limit': limits.get('max_conversations'),
                'percentage': calc_percentage(usage['total_conversations'], limits.get('max_conversations'))
            },
        }

    @classmethod
    def update_org_limits(cls, org_id, new_limits: dict):
        """
        Update organization limits. Creates or updates the current period quota.
        This is used by admin to set custom limits.
        """
        now = timezone.now()
        # Get or create current period quota
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            end_of_month = start_of_month.replace(year=now.year + 1, month=1) - timezone.timedelta(seconds=1)
        else:
            end_of_month = start_of_month.replace(month=now.month + 1) - timezone.timedelta(seconds=1)

        quota, created = Quota.objects.get_or_create(
            org_id=org_id,
            period_start=start_of_month,
            period_end=end_of_month,
            defaults={'limits': new_limits, 'usage': {}}
        )

        if not created:
            # Merge new limits with existing
            existing_limits = quota.limits or {}
            existing_limits.update(new_limits)
            quota.limits = existing_limits
            quota.save(update_fields=['limits', 'updated_at'])

        logger.info(f"Updated limits for org {org_id}: {new_limits}")
        return quota
