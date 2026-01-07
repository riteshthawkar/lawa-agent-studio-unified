from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """Custom exception handler for consistent error responses"""
    
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    # Handle standard JSON decode errors if not caught by DRF
    if response is None:
        from json import JSONDecodeError
        if isinstance(exc, JSONDecodeError):
            response = Response(
                {'detail': 'JSON parse error - invalid format'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    if response is not None:
        # Get the request for additional context
        request = context.get('request')
        request_id = getattr(request, 'request_id', '') if request else ''
        
        # Customize the error response
        custom_response_data = {
            'error': {
                'code': getattr(exc, 'code', 'unknown_error'),
                'message': str(exc),
                'details': getattr(exc, 'details', None),
                'request_id': request_id,
            }
        }
        
        # Add validation errors if present
        if hasattr(response, 'data') and isinstance(response.data, dict):
            if 'detail' in response.data:
                custom_response_data['error']['message'] = response.data['detail']
            elif 'non_field_errors' in response.data:
                custom_response_data['error']['message'] = response.data['non_field_errors'][0]
            else:
                custom_response_data['error']['validation_errors'] = response.data
        
        response.data = custom_response_data
        
        # Log the error
        logger.error(
            f"API Error: {exc}",
            extra={
                'request_id': request_id,
                'status_code': response.status_code,
                'error_type': type(exc).__name__,
            }
        )
    
    return response


class LawaPlatformException(Exception):
    """Base exception for Lawa Platform"""
    
    def __init__(self, message, code=None, details=None):
        self.message = message
        self.code = code or 'unknown_error'
        self.details = details
        super().__init__(message)


class OrganizationAccessDenied(LawaPlatformException):
    """Raised when user doesn't have access to organization"""
    
    def __init__(self, message="Organization access denied", details=None):
        super().__init__(message, 'organization_access_denied', details)


class QuotaExceeded(LawaPlatformException):
    """Raised when quota limits are exceeded"""
    
    def __init__(self, message="Quota exceeded", details=None):
        super().__init__(message, 'quota_exceeded', details)


class SiteNotVerified(LawaPlatformException):
    """Raised when site is not verified"""
    
    def __init__(self, message="Site not verified", details=None):
        super().__init__(message, 'site_not_verified', details)


class InvalidWebhookSignature(LawaPlatformException):
    """Raised when webhook signature is invalid"""
    
    def __init__(self, message="Invalid webhook signature", details=None):
        super().__init__(message, 'invalid_webhook_signature', details)
