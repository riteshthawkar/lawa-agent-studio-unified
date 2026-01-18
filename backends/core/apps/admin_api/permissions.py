"""
Admin API Permissions

Provides granular permission classes for admin functionality:
- Basic admin access (IsAdminUser)
- IP allowlist restrictions (AdminIPAllowlist)
- Role-based permissions (ReadOnlyAdmin, UserManagerAdmin, etc.)
- Superuser-only operations (IsSuperAdmin)
"""

from rest_framework import permissions
from django.conf import settings
from django.core.cache import cache
import ipaddress
import logging

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Take the first IP in the chain (client IP)
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class IsAdminUser(permissions.BasePermission):
    """
    Allows access only to admin users (staff members).
    """
    message = "Admin access required."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsSuperAdmin(permissions.BasePermission):
    """
    Allows access only to superuser admins.

    Use for highly sensitive operations:
    - Managing other admin accounts
    - System configuration changes
    - Viewing all audit logs
    """
    message = "Superuser access required."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_superuser
        )


class AdminIPAllowlist(permissions.BasePermission):
    """
    Restricts admin access to specific IP addresses or CIDR ranges.

    Configure in settings:
        ADMIN_IP_ALLOWLIST = ['10.0.0.0/8', '192.168.1.100', '2001:db8::/32']

    Set ADMIN_IP_ALLOWLIST_ENABLED = True to enable.
    When disabled or not configured, all IPs are allowed.
    """
    message = "Your IP address is not authorized for admin access."

    def has_permission(self, request, view):
        # Check if IP allowlist is enabled
        if not getattr(settings, 'ADMIN_IP_ALLOWLIST_ENABLED', False):
            return True

        allowlist = getattr(settings, 'ADMIN_IP_ALLOWLIST', [])
        if not allowlist:
            return True

        client_ip = get_client_ip(request)
        if not client_ip:
            logger.warning("Could not determine client IP for admin access check")
            return False

        try:
            client_ip_obj = ipaddress.ip_address(client_ip)

            for allowed in allowlist:
                try:
                    # Try as network (CIDR notation)
                    if '/' in str(allowed):
                        network = ipaddress.ip_network(allowed, strict=False)
                        if client_ip_obj in network:
                            return True
                    else:
                        # Try as single IP
                        if client_ip_obj == ipaddress.ip_address(allowed):
                            return True
                except ValueError:
                    logger.warning(f"Invalid IP/network in allowlist: {allowed}")
                    continue

            logger.warning(
                f"Admin access denied for IP {client_ip}",
                extra={'ip': client_ip, 'user': getattr(request.user, 'email', 'anonymous')}
            )
            return False

        except ValueError:
            logger.error(f"Invalid client IP address: {client_ip}")
            return False


class AdminWithIPCheck(permissions.BasePermission):
    """
    Combined permission: must be admin AND pass IP allowlist check.
    """
    message = "Admin access required from authorized IP."

    def has_permission(self, request, view):
        # First check admin status
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        # Then check IP allowlist
        return AdminIPAllowlist().has_permission(request, view)


# ===========================================
# Role-Based Admin Permissions
# ===========================================

class AdminRole:
    """Admin role constants."""
    SUPERUSER = 'superuser'
    USER_MANAGER = 'user_manager'
    SUPPORT = 'support'
    BILLING = 'billing'
    READ_ONLY = 'read_only'


def get_admin_roles(user):
    """
    Get admin roles for a user.

    Roles can be stored in:
    1. User model field (e.g., user.admin_roles)
    2. Cache (for performance)
    3. Separate AdminRole model

    For now, derive from user flags:
    - is_superuser -> all roles
    - is_staff -> basic admin access
    """
    if not user or not user.is_authenticated:
        return []

    # Check cache first
    cache_key = f'admin_roles_{user.id}'
    cached_roles = cache.get(cache_key)
    if cached_roles is not None:
        return cached_roles

    roles = []

    if user.is_superuser:
        roles = [
            AdminRole.SUPERUSER,
            AdminRole.USER_MANAGER,
            AdminRole.SUPPORT,
            AdminRole.BILLING,
            AdminRole.READ_ONLY,
        ]
    elif user.is_staff:
        # Check for specific role assignments
        # This can be extended to use a database model
        admin_roles = getattr(user, 'admin_roles', None)
        if admin_roles:
            roles = admin_roles if isinstance(admin_roles, list) else [admin_roles]
        else:
            # Default staff user gets read-only and support
            roles = [AdminRole.READ_ONLY, AdminRole.SUPPORT]

    # Cache for 5 minutes
    cache.set(cache_key, roles, 300)
    return roles


class ReadOnlyAdmin(permissions.BasePermission):
    """
    Permission for read-only admin operations.

    Allows GET, HEAD, OPTIONS requests only.
    All admins have this permission.
    """
    message = "Read-only admin access required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        # Read-only methods allowed for all admins
        if request.method in permissions.SAFE_METHODS:
            return True

        # For write operations, need more specific permissions
        return False


class UserManagerAdmin(permissions.BasePermission):
    """
    Permission for user management operations.

    Required for:
    - Creating/updating/deleting users
    - Suspending/activating users
    - Bulk user operations
    """
    message = "User management permission required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        # Superusers always have access
        if request.user.is_superuser:
            return True

        roles = get_admin_roles(request.user)
        return AdminRole.USER_MANAGER in roles or AdminRole.SUPERUSER in roles


class SupportAdmin(permissions.BasePermission):
    """
    Permission for support operations.

    Required for:
    - Viewing user details
    - Impersonating users
    - Managing feedback
    - Viewing chat sessions
    """
    message = "Support admin permission required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        if request.user.is_superuser:
            return True

        roles = get_admin_roles(request.user)
        return AdminRole.SUPPORT in roles or AdminRole.SUPERUSER in roles


class BillingAdmin(permissions.BasePermission):
    """
    Permission for billing and subscription operations.

    Required for:
    - Viewing/modifying subscriptions
    - Managing quotas
    - Viewing payment information
    - Upgrading/downgrading tiers
    """
    message = "Billing admin permission required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        if request.user.is_superuser:
            return True

        roles = get_admin_roles(request.user)
        return AdminRole.BILLING in roles or AdminRole.SUPERUSER in roles


class CanImpersonate(permissions.BasePermission):
    """
    Permission for user impersonation.

    Strictly controlled - requires support role AND explicit impersonation permission.
    Impersonation is logged for audit purposes.
    """
    message = "Impersonation permission required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        # Only superusers and explicitly authorized support admins
        if request.user.is_superuser:
            return True

        # Check for explicit impersonation permission
        can_impersonate = getattr(request.user, 'can_impersonate', False)
        if can_impersonate:
            roles = get_admin_roles(request.user)
            return AdminRole.SUPPORT in roles

        return False


class CanPerformBulkOperations(permissions.BasePermission):
    """
    Permission for bulk operations.

    Required for operations that affect multiple records:
    - Bulk user suspend/activate/delete
    - Bulk feedback updates
    - Mass data exports
    """
    message = "Bulk operations permission required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        # Only superusers and user managers can do bulk operations
        if request.user.is_superuser:
            return True

        roles = get_admin_roles(request.user)
        return AdminRole.USER_MANAGER in roles


class CanExportData(permissions.BasePermission):
    """
    Permission for data export operations.

    Required for:
    - Exporting user lists
    - Exporting job data
    - Exporting analytics
    """
    message = "Data export permission required."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            return False

        # Superusers always can export
        if request.user.is_superuser:
            return True

        # Check for explicit export permission
        can_export = getattr(request.user, 'can_export_data', True)  # Default allow for admins
        return can_export


class CanManageAdmins(permissions.BasePermission):
    """
    Permission for managing admin accounts.

    Only superusers can:
    - Create admin accounts
    - Modify admin permissions
    - Deactivate admin accounts
    """
    message = "Only superusers can manage admin accounts."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_superuser
        )
