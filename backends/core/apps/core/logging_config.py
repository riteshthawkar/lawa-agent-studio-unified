"""
Structured logging configuration and utilities.

This module provides consistent structured logging across the platform
with JSON formatting and request context tracking.
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    """

    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id
        if hasattr(record, 'org_id'):
            log_data['org_id'] = record.org_id
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        if hasattr(record, 'path'):
            log_data['path'] = record.path
        if hasattr(record, 'method'):
            log_data['method'] = record.method

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add any other extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'message', 'pathname', 'process', 'processName',
                          'relativeCreated', 'thread', 'threadName', 'exc_info',
                          'exc_text', 'stack_info', 'user_id', 'org_id', 'request_id',
                          'path', 'method']:
                log_data[key] = value

        return json.dumps(log_data)


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured Logger instance
    """
    return logging.getLogger(name)


def log_request(
    logger: logging.Logger,
    request,
    message: str,
    level: str = 'info',
    extra: Optional[Dict[str, Any]] = None
):
    """
    Log an HTTP request with context.

    Args:
        logger: Logger instance
        request: Django request object
        message: Log message
        level: Log level ('debug', 'info', 'warning', 'error')
        extra: Additional fields to log

    Example:
        >>> logger = get_logger(__name__)
        >>> log_request(logger, request, "User logged in", extra={'action': 'login'})
    """
    log_data = {
        'user_id': str(request.user.id) if request.user.is_authenticated else None,
        'path': request.path,
        'method': request.method,
        'ip': get_client_ip(request),
    }

    if extra:
        log_data.update(extra)

    log_func = getattr(logger, level.lower())
    log_func(message, extra=log_data)


def log_error(
    logger: logging.Logger,
    message: str,
    exception: Optional[Exception] = None,
    extra: Optional[Dict[str, Any]] = None
):
    """
    Log an error with optional exception details.

    Args:
        logger: Logger instance
        message: Error message
        exception: Optional exception object
        extra: Additional fields to log

    Example:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_error(logger, "Operation failed", exception=e, extra={'operation': 'risky'})
    """
    log_data = {}

    if exception:
        log_data['exception_type'] = type(exception).__name__
        log_data['exception_message'] = str(exception)

    if extra:
        log_data.update(extra)

    logger.error(message, extra=log_data, exc_info=exception is not None)


def get_client_ip(request) -> str:
    """
    Extract client IP from request.

    Args:
        request: Django request object

    Returns:
        String IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
