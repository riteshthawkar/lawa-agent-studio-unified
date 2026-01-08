from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """Custom exception handler for consistent error responses"""
    
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    # If response is None, it's an unhandled exception (System Error / 500)
    if response is None:
        # Get request ID for logging
        request = context.get('request')
        request_id = getattr(request, 'request_id', 'unknown') if request else 'unknown'
        
        # Log the full traceback internally
        logger.error(
            f"Unhandled System Error: {exc}",
            extra={
                'request_id': request_id,
                'error_type': type(exc).__name__,
            },
            exc_info=True
        )
        
        # Return generic error to user
        response = Response(
            {
                'error': {
                    'code': 'internal_server_error',
                    'message': 'An unexpected system error occurred. Please try again later.',
                    'request_id': request_id
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        # We return early since we already formatted the response
        return response

    if response is not None:
        # Get the request for additional context
        request = context.get('request')
        request_id = getattr(request, 'request_id', '') if request else ''
        
        # Determine error code
        code = getattr(exc, 'code', None)
        if not code:
            if hasattr(exc, 'get_codes'):
                codes = exc.get_codes()
                if isinstance(codes, str):
                    code = codes
                elif isinstance(codes, list) and codes:
                    code = codes[0]
                elif isinstance(codes, dict):
                    # For field errors, just use generic validation_error
                    code = 'validation_error'
            
        if not code:
            code = getattr(exc, 'default_code', 'api_error')

        # Customize the error response
        custom_response_data = {
            'error': {
                'code': code,
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
        logger.warning(
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


class ChatbotServiceException(LawaPlatformException):
    """Raised when external chatbot service fails"""
    
    def __init__(self, message, status_code=503, details=None):
        self.status_code = status_code
        super().__init__(message, 'chatbot_service_error', details)
