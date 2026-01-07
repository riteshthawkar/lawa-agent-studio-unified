"""
Service-to-service authentication for backend APIs.
These permissions secure internal endpoints called by the FastAPI indexing worker.
"""
from rest_framework.permissions import BasePermission
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class IsServiceAuthenticated(BasePermission):
    """
    Permission class for backend-to-backend API calls.
    
    Authenticates using a shared secret token passed in the Authorization header.
    This is used for internal service communication (e.g., FastAPI worker → Django).
    
    The token is configured via INDEXING_API_TOKEN in settings.
    """
    
    def has_permission(self, request, view):
        # Get the expected token from settings
        expected_token = getattr(settings, 'INDEXING_API_TOKEN', '')
        
        # If no token is configured, deny access (fail secure)
        if not expected_token:
            logger.warning("INDEXING_API_TOKEN not configured - denying service access")
            return False
        
        # Extract token from Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if auth_header.startswith('Bearer '):
            provided_token = auth_header[7:]  # Remove 'Bearer ' prefix
        elif auth_header.startswith('Token '):
            provided_token = auth_header[6:]  # Remove 'Token ' prefix
        else:
            provided_token = auth_header
        
        # Constant-time comparison to prevent timing attacks
        import hmac
        is_valid = hmac.compare_digest(provided_token, expected_token)
        
        if not is_valid:
            logger.warning(f"Invalid service token from {request.META.get('REMOTE_ADDR')}")
        
        return is_valid


class IsServiceOrAuthenticated(BasePermission):
    """
    Permission class that allows either:
    1. Service-to-service authentication (via INDEXING_API_TOKEN)
    2. Standard user authentication (via JWT)
    
    Useful for endpoints that can be called by both internal services and users.
    """
    
    def has_permission(self, request, view):
        # First, check service token
        service_auth = IsServiceAuthenticated()
        if service_auth.has_permission(request, view):
            return True
        
        # Otherwise, check if user is authenticated
        return request.user and request.user.is_authenticated
