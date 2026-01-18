"""
Advanced rate limiting with organization and user-level controls.

Provides flexible rate limiting that supports:
- Per-user limits
- Per-organization limits
- Per-endpoint limits
- Custom rate limits based on subscription tiers
"""

from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle
from django.core.cache import cache
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class OrganizationRateThrottle(SimpleRateThrottle):
    """
    Rate limit based on organization membership.

    Organizations can have custom rate limits based on their subscription tier.
    Falls back to default rate if organization has no custom limit.
    """
    scope = 'organization'

    def get_cache_key(self, request, view):
        """Generate cache key based on organization ID."""
        if not request.user or not request.user.is_authenticated:
            return self.get_ident(request)  # Fall back to IP-based for anonymous

        # Get organization ID from request (set by OrganizationMiddleware)
        org_id = getattr(request, 'org_id', None)

        if not org_id:
            # User not in any organization - use user-based limit
            return f'throttle_user_{request.user.id}'

        return f'throttle_org_{org_id}'

    def get_rate(self):
        """
        Get rate limit for the organization.

        Can be customized based on organization tier/subscription.
        """
        # Default rate from settings
        return settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {}).get(self.scope, '1000/hour')


class TieredOrganizationThrottle(OrganizationRateThrottle):
    """
    Organization rate limit with tier-based limits.

    Supports different rate limits for different subscription tiers:
    - Basic tier (free): 100/hour
    - Premium tier: 5000/hour
    - Enterprise tier: 50000/hour
    """
    scope = 'tiered_organization'

    TIER_LIMITS = {
        'basic': '100/hour',
        'premium': '5000/hour',
        'enterprise': '50000/hour',
    }

    def get_rate(self):
        """Get rate based on organization's subscription tier."""
        if not hasattr(self, 'request') or not self.request:
            return self.TIER_LIMITS['basic']

        org_id = getattr(self.request, 'org_id', None)

        if not org_id:
            return self.TIER_LIMITS['basic']

        # Get organization tier from cache or database
        cache_key = f'org_tier_{org_id}'
        tier = cache.get(cache_key)

        if tier is None:
            # Query organization tier from database
            try:
                from apps.organizations.models import Organization
                org = Organization.objects.get(id=org_id)
                tier = getattr(org, 'plan_tier', 'basic')  # Use correct field name
                # Cache for 1 hour
                cache.set(cache_key, tier, 3600)
            except Exception as e:
                logger.warning(f"Failed to get organization tier: {e}")
                tier = 'basic'

        return self.TIER_LIMITS.get(tier, self.TIER_LIMITS['basic'])


class PerUserThrottle(UserRateThrottle):
    """
    Rate limit per authenticated user.

    Uses user ID for rate limiting. Anonymous users are throttled by IP.
    """
    scope = 'user'

    def get_cache_key(self, request, view):
        """Generate cache key based on user ID."""
        if not request.user or not request.user.is_authenticated:
            return self.get_ident(request)  # Fall back to IP-based for anonymous

        return f'throttle_user_{request.user.id}'


class BurstRateThrottle(SimpleRateThrottle):
    """
    Burst rate limiter to prevent rapid successive requests.

    Allows short bursts of activity but prevents sustained high-rate attacks.
    Example: 30 requests per minute
    """
    scope = 'burst'

    def get_cache_key(self, request, view):
        """Generate cache key based on user or IP."""
        if request.user and request.user.is_authenticated:
            return f'throttle_burst_user_{request.user.id}'
        return f'throttle_burst_ip_{self.get_ident(request)}'


class SustainedRateThrottle(SimpleRateThrottle):
    """
    Sustained rate limiter for longer-term limits.

    Prevents sustained high usage over longer periods.
    Example: 10000 requests per day
    """
    scope = 'sustained'

    def get_cache_key(self, request, view):
        """Generate cache key based on user or IP."""
        if request.user and request.user.is_authenticated:
            return f'throttle_sustained_user_{request.user.id}'
        return f'throttle_sustained_ip_{self.get_ident(request)}'


class EndpointSpecificThrottle(SimpleRateThrottle):
    """
    Endpoint-specific rate limiting.

    Allows different rate limits for different endpoints.
    Configure in view with: throttle_scope = 'endpoint_name'
    """

    def get_cache_key(self, request, view):
        """Generate cache key based on endpoint and user/IP."""
        # Get scope from view
        scope = getattr(view, 'throttle_scope', 'default')

        if request.user and request.user.is_authenticated:
            ident = f'user_{request.user.id}'
        else:
            ident = f'ip_{self.get_ident(request)}'

        return f'throttle_{scope}_{ident}'

    def get_rate(self):
        """Get rate limit for specific endpoint."""
        # This should be set on the view
        if hasattr(self, 'view') and hasattr(self.view, 'throttle_scope'):
            scope = self.view.throttle_scope
            rates = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
            return rates.get(scope, '100/hour')

        return '100/hour'


class AnonRateThrottle(SimpleRateThrottle):
    """
    Rate limit for anonymous (unauthenticated) users.

    More restrictive than authenticated user limits.
    """
    scope = 'anon'

    def get_cache_key(self, request, view):
        """Generate cache key based on IP for anonymous users."""
        if request.user and request.user.is_authenticated:
            return None  # Only throttle anonymous users

        return f'throttle_anon_{self.get_ident(request)}'


# Custom throttle for expensive operations
class ExpensiveOperationThrottle(SimpleRateThrottle):
    """
    Restrictive rate limit for expensive operations.

    Use for operations that are resource-intensive:
    - File uploads
    - Bulk operations
    - Report generation
    - AI/ML processing
    """
    scope = 'expensive'

    def get_cache_key(self, request, view):
        """Generate cache key for expensive operations."""
        if request.user and request.user.is_authenticated:
            return f'throttle_expensive_user_{request.user.id}'
        return f'throttle_expensive_ip_{self.get_ident(request)}'


# Helper function to check rate limit without consuming it
def check_rate_limit(request, scope='user', increment=False):
    """
    Check if request would exceed rate limit.

    Args:
        request: Django request object
        scope: Rate limit scope to check
        increment: If True, consume a request from the limit

    Returns:
        dict: {
            'allowed': bool,
            'limit': int,
            'remaining': int,
            'reset_time': int (unix timestamp)
        }
    """
    from rest_framework.request import Request
    from rest_framework.views import APIView

    # Get appropriate throttle class
    throttle_classes = {
        'user': PerUserThrottle,
        'organization': OrganizationRateThrottle,
        'burst': BurstRateThrottle,
        'sustained': SustainedRateThrottle,
        'anon': AnonRateThrottle,
        'expensive': ExpensiveOperationThrottle,
    }

    throttle_class = throttle_classes.get(scope, PerUserThrottle)
    throttle = throttle_class()

    # Convert to DRF request if needed
    if not isinstance(request, Request):
        request = Request(request)

    # Mock view for throttle check
    view = APIView()

    # Check if allowed
    allowed = throttle.allow_request(request, view)

    return {
        'allowed': allowed,
        'wait_time': throttle.wait() if not allowed else 0,
    }


# ===========================================
# Admin-Specific Rate Limiting
# ===========================================

class AdminRateThrottle(SimpleRateThrottle):
    """
    Rate limit for admin API endpoints.

    More restrictive than regular user limits to prevent abuse
    of admin privileges.
    """
    scope = 'admin'
    rate = '100/minute'

    def get_cache_key(self, request, view):
        """Generate cache key based on admin user ID."""
        if not request.user or not request.user.is_authenticated:
            return None  # Only authenticated admins

        if not request.user.is_staff:
            return None  # Only admin users

        return f'throttle_admin_{request.user.id}'


class AdminBurstThrottle(SimpleRateThrottle):
    """
    Burst protection for admin endpoints.

    Prevents rapid-fire admin operations which could indicate
    compromised credentials or automated attacks.
    """
    scope = 'admin_burst'
    rate = '30/minute'

    def get_cache_key(self, request, view):
        """Generate cache key for admin burst limiting."""
        if not request.user or not request.user.is_authenticated:
            return None

        if not request.user.is_staff:
            return None

        return f'throttle_admin_burst_{request.user.id}'


class AdminLoginThrottle(SimpleRateThrottle):
    """
    Strict rate limit for admin login attempts.

    Prevents brute force attacks on admin accounts.
    Uses IP-based limiting since user isn't authenticated yet.
    """
    scope = 'admin_login'
    rate = '5/minute'

    def get_cache_key(self, request, view):
        """Generate cache key based on IP address."""
        return f'throttle_admin_login_{self.get_ident(request)}'


class AdminLoginDailyThrottle(SimpleRateThrottle):
    """
    Daily limit for admin login attempts per IP.

    Provides long-term protection against distributed attacks.
    """
    scope = 'admin_login_daily'
    rate = '20/day'

    def get_cache_key(self, request, view):
        """Generate cache key based on IP address."""
        return f'throttle_admin_login_daily_{self.get_ident(request)}'


class AdminSensitiveOperationThrottle(SimpleRateThrottle):
    """
    Very restrictive throttle for sensitive admin operations.

    Use for:
    - User deletion
    - Bulk operations
    - Impersonation
    - Permission changes
    """
    scope = 'admin_sensitive'
    rate = '10/hour'

    def get_cache_key(self, request, view):
        """Generate cache key for sensitive operations."""
        if not request.user or not request.user.is_authenticated:
            return None

        return f'throttle_admin_sensitive_{request.user.id}'


class AdminExportThrottle(SimpleRateThrottle):
    """
    Rate limit for admin data export operations.

    Prevents mass data exfiltration through export endpoints.
    """
    scope = 'admin_export'
    rate = '5/hour'

    def get_cache_key(self, request, view):
        """Generate cache key for export operations."""
        if not request.user or not request.user.is_authenticated:
            return None

        return f'throttle_admin_export_{request.user.id}'


# Decorator for view functions
def rate_limit(scope='user', rate=None):
    """
    Decorator to apply rate limiting to function-based views.

    Args:
        scope: Rate limit scope ('user', 'organization', etc.)
        rate: Optional custom rate (e.g., '100/hour')

    Example:
        @rate_limit(scope='expensive', rate='10/hour')
        def expensive_operation(request):
            ...
    """
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            result = check_rate_limit(request, scope=scope, increment=True)

            if not result['allowed']:
                from rest_framework.response import Response
                from rest_framework import status

                return Response(
                    {
                        'error': 'Rate limit exceeded',
                        'detail': f"Please wait {result['wait_time']:.0f} seconds before retrying",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={
                        'Retry-After': str(int(result['wait_time'])),
                    }
                )

            return view_func(request, *args, **kwargs)

        return wrapper
    return decorator
