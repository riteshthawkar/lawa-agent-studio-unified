"""
Custom error handlers for standardized API error responses.

Provides consistent error response format across all API endpoints
following RFC 9457 (Problem Details for HTTP APIs) inspired structure.
"""

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework.exceptions import (
    ValidationError,
    PermissionDenied,
    NotFound,
    AuthenticationFailed,
    NotAuthenticated,
    APIException
)
import uuid
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


# Custom Exception Classes
class BusinessLogicError(APIException):
    """Base exception for business logic errors"""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = 'Business logic error occurred'
    default_code = 'business_logic_error'


class ResourceNotFoundError(NotFound):
    """Exception for when a resource is not found"""
    default_detail = 'The requested resource was not found'
    default_code = 'resource_not_found'


class ResourceConflictError(APIException):
    """Exception for resource conflicts (e.g., duplicate entries)"""
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Resource conflict occurred'
    default_code = 'resource_conflict'


class QuotaExceededError(APIException):
    """Exception for when quota limits are exceeded"""
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = 'Quota limit exceeded'
    default_code = 'quota_exceeded'


class ExternalServiceError(APIException):
    """Exception for external service failures"""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'External service unavailable'
    default_code = 'external_service_error'


class InvalidParameterError(ValidationError):
    """Exception for invalid request parameters"""
    default_detail = 'Invalid parameter provided'
    default_code = 'invalid_parameter'


def custom_exception_handler(exc, context):
    """
    Custom exception handler that returns standardized error responses.

    Args:
        exc: The exception that was raised
        context: Context dict containing request and view info

    Returns:
        Response with standardized error format
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    # Generate unique request ID for tracking
    request_id = str(uuid.uuid4())

    # Get request from context if available
    request = context.get('request')
    if request:
        # Store request_id in request for logging
        request.request_id = request_id

    # If DRF handled the exception, format it
    if response is not None:
        error_data = format_error_response(
            exc=exc,
            response=response,
            request_id=request_id,
            context=context
        )
        response.data = error_data

        # Log the error
        log_error(exc, context, request_id, response.status_code)

        return response

    # Handle Django's built-in exceptions that DRF doesn't handle
    if isinstance(exc, DjangoValidationError):
        error_data = format_error_response(
            exc=exc,
            response=None,
            request_id=request_id,
            context=context,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code='validation_error'
        )
        log_error(exc, context, request_id, status.HTTP_400_BAD_REQUEST)
        return Response(error_data, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, Http404):
        error_data = format_error_response(
            exc=exc,
            response=None,
            request_id=request_id,
            context=context,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code='not_found'
        )
        log_error(exc, context, request_id, status.HTTP_404_NOT_FOUND)
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)

    # For unhandled exceptions, return 500
    error_data = format_error_response(
        exc=exc,
        response=None,
        request_id=request_id,
        context=context,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code='internal_server_error'
    )

    # Log unhandled exceptions with full traceback
    logger.exception(
        f"Unhandled exception occurred",
        extra={
            'request_id': request_id,
            'exception_type': type(exc).__name__,
            'exception_message': str(exc)
        }
    )

    return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def format_error_response(exc, response, request_id, context, status_code=None, error_code=None):
    """
    Format error response in standardized structure.

    Args:
        exc: The exception
        response: DRF response object (if available)
        request_id: Unique request identifier
        context: Context dict
        status_code: HTTP status code (optional)
        error_code: Error code string (optional)

    Returns:
        Dict with standardized error structure
    """
    # Extract error details
    if response is not None:
        error_detail = response.data
        status_code = response.status_code
    else:
        error_detail = str(exc)
        status_code = status_code or status.HTTP_500_INTERNAL_SERVER_ERROR

    # Determine error code
    if error_code is None:
        error_code = getattr(exc, 'default_code', 'error')

    # Determine error message
    if isinstance(error_detail, dict):
        # DRF validation errors or custom structured errors
        if 'detail' in error_detail:
            message = error_detail['detail']
            details = {k: v for k, v in error_detail.items() if k != 'detail'}
        else:
            message = get_primary_error_message(exc)
            details = error_detail
    elif isinstance(error_detail, list):
        message = error_detail[0] if error_detail else str(exc)
        details = {'errors': error_detail}
    else:
        message = str(error_detail)
        details = {}

    # Build standardized error response
    error_response = {
        'error': {
            'code': error_code,
            'message': message,
        },
        'meta': {
            'request_id': request_id,
            'timestamp': timezone.now().isoformat()
        }
    }

    # Add details if present
    if details:
        error_response['error']['details'] = details

    # Add status code for reference
    error_response['meta']['status_code'] = status_code

    return error_response


def get_primary_error_message(exc):
    """
    Extract primary error message from exception.

    Args:
        exc: The exception

    Returns:
        String error message
    """
    if hasattr(exc, 'detail'):
        detail = exc.detail
        if isinstance(detail, dict):
            # Return first error message
            for key, value in detail.items():
                if isinstance(value, list):
                    return value[0] if value else str(exc)
                return str(value)
        elif isinstance(detail, list):
            return detail[0] if detail else str(exc)
        return str(detail)

    return str(exc)


def log_error(exc, context, request_id, status_code):
    """
    Log error with contextual information.

    Args:
        exc: The exception
        context: Context dict
        request_id: Unique request identifier
        status_code: HTTP status code
    """
    request = context.get('request')
    view = context.get('view')

    log_data = {
        'request_id': request_id,
        'exception_type': type(exc).__name__,
        'exception_message': str(exc),
        'status_code': status_code,
        'view': view.__class__.__name__ if view else None,
    }

    if request:
        log_data.update({
            'path': request.path,
            'method': request.method,
            'user_id': str(request.user.id) if request.user.is_authenticated else None,
        })

    # Log at appropriate level based on status code
    if status_code >= 500:
        logger.error(
            f"Server error occurred: {type(exc).__name__}",
            extra=log_data,
            exc_info=True
        )
    elif status_code >= 400:
        logger.warning(
            f"Client error occurred: {type(exc).__name__}",
            extra=log_data
        )
    else:
        logger.info(
            f"Exception occurred: {type(exc).__name__}",
            extra=log_data
        )


# Helper function to raise standardized errors
def raise_error(error_class, message, details=None):
    """
    Raise a standardized error with optional details.

    Args:
        error_class: Exception class to raise
        message: Error message
        details: Optional dict of additional error details

    Raises:
        error_class instance
    """
    error = error_class(message)
    if details:
        error.detail = {'detail': message, **details}
    raise error
