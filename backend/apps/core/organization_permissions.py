"""
Organization-based access control permissions.

This module provides permission classes and utilities for enforcing
multi-tenant organization-based access control across the platform.
"""

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, NotFound
from django.shortcuts import get_object_or_404
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession
import logging

logger = logging.getLogger(__name__)


class OrganizationAccessError(PermissionDenied):
    """Raised when user doesn't have access to the requested organization."""
    default_detail = "You do not have access to this organization."
    default_code = "organization_access_denied"


class ResourceNotInOrganizationError(PermissionDenied):
    """Raised when a resource doesn't belong to user's organization."""
    default_detail = "This resource does not belong to your organization."
    default_code = "resource_not_in_organization"


def get_user_organizations(user):
    """
    Get all organizations the user is a member of.

    Args:
        user: The User instance

    Returns:
        QuerySet of Organization instances
    """
    if not user or not user.is_authenticated:
        return Organization.objects.none()

    return Organization.objects.filter(
        memberships__user=user,
        status='active'
    ).distinct()


def check_organization_access(user, org_id):
    """
    Check if user has access to the specified organization.

    Args:
        user: The User instance
        org_id: Organization UUID

    Returns:
        Organization instance if access granted

    Raises:
        OrganizationAccessError: If user doesn't have access
    """
    if not user or not user.is_authenticated:
        raise OrganizationAccessError("Authentication required")

    try:
        organization = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        raise NotFound("Organization not found")

    # Check if user is a member of this organization
    has_access = Membership.objects.filter(
        user=user,
        organization=organization
    ).exists()

    if not has_access:
        logger.warning(
            f"Organization access denied: user={user.id} org={org_id}",
            extra={'user_id': str(user.id), 'org_id': str(org_id)}
        )
        raise OrganizationAccessError()

    return organization


def check_site_access(user, site_id, org_id=None):
    """
    Check if user has access to the specified site.

    Args:
        user: The User instance
        site_id: Site UUID
        org_id: Optional organization UUID for additional validation

    Returns:
        Site instance if access granted

    Raises:
        ResourceNotInOrganizationError: If site doesn't belong to user's org
    """
    if not user or not user.is_authenticated:
        raise OrganizationAccessError("Authentication required")

    try:
        # Note: org_id is UUIDField, not ForeignKey, so no select_related
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        raise NotFound("Site not found")

    # If site has no org_id, allow access (legacy data)
    if not site.org_id:
        logger.warning(
            f"Site {site_id} has no org_id - legacy data",
            extra={'site_id': str(site_id)}
        )
        return site

    # Check if user has access to the site's organization
    user_orgs = get_user_organizations(user)

    if site.org_id not in user_orgs.values_list('id', flat=True):
        logger.warning(
            f"Site access denied: user={user.id} site={site_id} org={site.org_id}",
            extra={'user_id': str(user.id), 'site_id': str(site_id), 'org_id': str(site.org_id)}
        )
        raise ResourceNotInOrganizationError("This site does not belong to your organization")

    # If org_id was provided, validate it matches
    if org_id and str(site.org_id) != str(org_id):
        raise ResourceNotInOrganizationError("Site does not belong to the specified organization")

    return site


def check_chatbot_access(user, chatbot_id, org_id=None):
    """
    Check if user has access to the specified chatbot.

    Args:
        user: The User instance
        chatbot_id: Chatbot UUID
        org_id: Optional organization UUID for additional validation

    Returns:
        Chatbot instance if access granted

    Raises:
        ResourceNotInOrganizationError: If chatbot doesn't belong to user's org
    """
    if not user or not user.is_authenticated:
        raise OrganizationAccessError("Authentication required")

    try:
        # Note: site_id is UUIDField, not ForeignKey, so no select_related
        chatbot = Chatbot.objects.get(id=chatbot_id)
    except Chatbot.DoesNotExist:
        raise NotFound("Chatbot not found")

    # Get the site and check access through it
    site = check_site_access(user, chatbot.site_id, org_id)

    return chatbot


def check_session_access(user, session_id, org_id=None):
    """
    Check if user has access to the specified chat session.

    Args:
        user: The User instance
        session_id: ChatSession UUID
        org_id: Optional organization UUID for additional validation

    Returns:
        ChatSession instance if access granted

    Raises:
        ResourceNotInOrganizationError: If session doesn't belong to user's org
    """
    if not user or not user.is_authenticated:
        raise OrganizationAccessError("Authentication required")

    try:
        session = ChatSession.objects.select_related('chatbot', 'site').get(id=session_id)
    except ChatSession.DoesNotExist:
        raise NotFound("Chat session not found")

    # Check access through the site
    if session.site_id:
        check_site_access(user, session.site_id, org_id)
    elif session.chatbot_id:
        check_chatbot_access(user, session.chatbot_id, org_id)
    else:
        logger.error(
            f"Session {session_id} has no site or chatbot reference",
            extra={'session_id': str(session_id)}
        )
        raise ResourceNotInOrganizationError("Invalid session configuration")

    return session


class IsOrganizationMember(permissions.BasePermission):
    """
    Permission class to check if user is a member of the organization.

    Expects the view to have:
    - get_organization() method, OR
    - organization attribute, OR
    - org_id in view kwargs
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Try to get organization from view
        org = None

        if hasattr(view, 'get_organization'):
            org = view.get_organization()
        elif hasattr(view, 'organization'):
            org = view.organization
        elif 'org_id' in view.kwargs:
            try:
                org = check_organization_access(request.user, view.kwargs['org_id'])
            except (OrganizationAccessError, NotFound):
                return False

        if not org:
            # No organization context - deny access
            return False

        # Check membership
        return Membership.objects.filter(
            user=request.user,
            organization=org
        ).exists()


class IsSiteOwner(permissions.BasePermission):
    """
    Permission class to check if user owns the site through their organization.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # obj should be a Site instance
        if not hasattr(obj, 'org_id') or not obj.org_id:
            # Legacy site without org - allow for now
            return True

        # Check if user has access to this site's organization
        try:
            check_organization_access(request.user, obj.org_id)
            return True
        except (OrganizationAccessError, NotFound):
            return False


class IsChatbotOwner(permissions.BasePermission):
    """
    Permission class to check if user owns the chatbot through their organization.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # obj should be a Chatbot instance
        try:
            check_chatbot_access(request.user, obj.id)
            return True
        except (OrganizationAccessError, ResourceNotInOrganizationError, NotFound):
            return False


class IsSessionOwner(permissions.BasePermission):
    """
    Permission class to check if user owns the chat session through their organization.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # obj should be a ChatSession instance
        try:
            check_session_access(request.user, obj.id)
            return True
        except (OrganizationAccessError, ResourceNotInOrganizationError, NotFound):
            return False


# Convenience decorators for function-based views
from functools import wraps
from django.http import JsonResponse


def require_organization_access(org_param='org_id'):
    """
    Decorator to require organization access for function-based views.

    Args:
        org_param: Name of the parameter containing org_id

    Example:
        @require_organization_access('org_id')
        def my_view(request, org_id):
            # org_id is validated, user has access
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            org_id = kwargs.get(org_param)

            if not org_id:
                return JsonResponse(
                    {'error': 'Organization ID required'},
                    status=400
                )

            try:
                check_organization_access(request.user, org_id)
            except OrganizationAccessError as e:
                return JsonResponse(
                    {'error': str(e)},
                    status=403
                )
            except NotFound as e:
                return JsonResponse(
                    {'error': str(e)},
                    status=404
                )

            return func(request, *args, **kwargs)

        return wrapper
    return decorator


def require_site_access(site_param='site_id'):
    """
    Decorator to require site access for function-based views.

    Args:
        site_param: Name of the parameter containing site_id

    Example:
        @require_site_access('site_id')
        def my_view(request, site_id):
            # site_id is validated, user has access
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            site_id = kwargs.get(site_param)

            if not site_id:
                return JsonResponse(
                    {'error': 'Site ID required'},
                    status=400
                )

            try:
                check_site_access(request.user, site_id)
            except (OrganizationAccessError, ResourceNotInOrganizationError) as e:
                return JsonResponse(
                    {'error': str(e)},
                    status=403
                )
            except NotFound as e:
                return JsonResponse(
                    {'error': str(e)},
                    status=404
                )

            return func(request, *args, **kwargs)

        return wrapper
    return decorator
