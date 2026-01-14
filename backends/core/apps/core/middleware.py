import uuid
import logging
import time
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.conf import settings

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(MiddlewareMixin):
    """Middleware to log requests with request ID and organization context"""
    
    def process_request(self, request):
        # Generate unique request ID
        request.request_id = str(uuid.uuid4())
        request.start_time = time.time()
        
        # Extract organization ID from JWT token or API key
        request.org_id = self._extract_org_id(request)
        
        # Log request
        logger.info(
            f"Request started",
            extra={
                'request_id': request.request_id,
                'org_id': request.org_id,
                'method': request.method,
                'path': request.path,
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'ip': self._get_client_ip(request),
            }
        )
    
    def process_response(self, request, response):
        # Calculate request duration
        if hasattr(request, 'start_time'):
            duration = (time.time() - request.start_time) * 1000  # Convert to milliseconds
        else:
            duration = 0
        
        # Log response
        logger.info(
            f"Request completed",
            extra={
                'request_id': getattr(request, 'request_id', ''),
                'org_id': getattr(request, 'org_id', ''),
                'status_code': response.status_code,
                'duration_ms': round(duration, 2),
            }
        )
        
        # Add request ID to response headers
        if hasattr(request, 'request_id'):
            response['X-Request-ID'] = request.request_id
        
        return response
    
    def _extract_org_id(self, request):
        """Extract organization ID from JWT token or API key"""
        # This will be implemented when we add JWT authentication
        # For now, return None
        return None
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class OrganizationMiddleware(MiddlewareMixin):
    """Middleware to extract and validate organization context"""
    
    def process_request(self, request):
        # Extract organization ID from various sources
        org_id = self._extract_org_id(request)
        request.org_id = org_id
        
        # Validate organization access if needed
        if org_id and not self._validate_org_access(request, org_id):
            return JsonResponse(
                {'error': 'Organization access denied'}, 
                status=403
            )
    
    def _extract_org_id(self, request):
        """Extract organization ID from JWT token, API key, URL, or user's primary organization"""
        # Check JWT token
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                token = auth_header.split(' ')[1]
                access_token = AccessToken(token)
                org_id = access_token.get('org_id')
                if org_id:
                    return org_id
            except Exception:
                pass

        # Check API key
        api_key = request.META.get('HTTP_X_API_KEY')
        if api_key:
            try:
                from apps.auth.models import APIKey
                import hashlib
                key_hash = hashlib.sha256(api_key.encode()).hexdigest()
                api_key_obj = APIKey.objects.get(token_hash=key_hash, is_active=True)
                return str(api_key_obj.org_id)
            except Exception:
                pass

        # Check URL parameter
        org_id = request.GET.get('org_id')
        if org_id:
            return org_id

        # If user is authenticated, get their primary organization
        if hasattr(request, 'user') and request.user.is_authenticated:
            try:
                from apps.organizations.models import Membership
                # Get the user's primary organization (first active membership)
                # In a production system, you might have a 'is_primary' flag
                membership = Membership.objects.filter(
                    user=request.user,
                    organization__status='active'
                ).first()

                if membership:
                    return str(membership.organization_id)
            except Exception as e:
                logger.warning(f"Error fetching user's organization: {str(e)}")

        return None
    
    def _validate_org_access(self, request, org_id):
        """Validate that the user has access to the organization"""
        # Skip validation for unauthenticated requests
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return True

        # Check if user is a member of the organization
        from apps.organizations.models import Membership
        try:
            Membership.objects.get(
                user=request.user,
                organization_id=org_id
            )
            return True
        except Membership.DoesNotExist:
            return False


class APIVersionMiddleware(MiddlewareMixin):
    """
    Middleware to add API version headers to all responses.

    Adds the following headers to API responses:
    - X-API-Version: The current API version (e.g., "1.0")
    - X-API-Deprecated: Warning if the API version is deprecated
    - Sunset: Date when the deprecated API will be removed (RFC 8594)
    """

    def process_response(self, request, response):
        # Only add headers to API endpoints
        if request.path.startswith('/v1/') or request.path.startswith('/api/'):
            # Add version header
            api_version = getattr(settings, 'API_VERSION', '1.0')
            response['X-API-Version'] = api_version

            # Add deprecation warning if applicable
            api_deprecated = getattr(settings, 'API_DEPRECATED', False)
            if api_deprecated:
                response['X-API-Deprecated'] = 'true'

                # Add sunset date if specified (RFC 8594)
                api_sunset_date = getattr(settings, 'API_SUNSET_DATE', None)
                if api_sunset_date:
                    response['Sunset'] = api_sunset_date

        return response


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to add security headers to all responses.

    Adds headers for:
    - X-Content-Type-Options: Prevent MIME sniffing
    - X-Frame-Options: Prevent clickjacking
    - Strict-Transport-Security: Enforce HTTPS (production only)
    """

    def process_response(self, request, response):
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'

        # Prevent clickjacking
        response['X-Frame-Options'] = 'DENY'

        # Enable HSTS in production (enforces HTTPS)
        if not settings.DEBUG:
            # max-age=31536000 = 1 year
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        return response
