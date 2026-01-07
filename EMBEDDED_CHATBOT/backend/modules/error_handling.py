#!/usr/bin/env python3
"""
Comprehensive Error Handling Module for LAWA Chatbot Backend
Provides structured error handling, logging, and user-friendly error responses.
"""

import logging
import traceback
from typing import Dict, Any, Optional
from enum import Enum
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

class ErrorSeverity(Enum):
    """Error severity levels for logging and alerting."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ErrorCategory(Enum):
    """Error categories for better organization."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    DATABASE = "database"
    EXTERNAL_SERVICE = "external_service"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"

class ChatbotError(Exception):
    """Base exception class for chatbot-specific errors."""
    
    def __init__(
        self, 
        message: str, 
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        user_message: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.user_message = user_message or self._get_default_user_message()
        self.error_code = error_code or self._get_default_error_code()
        self.details = details or {}
        self.timestamp = datetime.utcnow()
    
    def _get_default_user_message(self) -> str:
        """Get default user-friendly message based on category."""
        messages = {
            ErrorCategory.AUTHENTICATION: "Authentication failed. Please check your credentials.",
            ErrorCategory.AUTHORIZATION: "You don't have permission to perform this action.",
            ErrorCategory.VALIDATION: "Invalid input provided. Please check your request.",
            ErrorCategory.DATABASE: "Database error occurred. Please try again later.",
            ErrorCategory.EXTERNAL_SERVICE: "External service is temporarily unavailable.",
            ErrorCategory.RATE_LIMIT: "Too many requests. Please slow down and try again.",
            ErrorCategory.TIMEOUT: "Request timed out. Please try again with a simpler question.",
            ErrorCategory.NETWORK: "Network error occurred. Please check your connection.",
            ErrorCategory.CONFIGURATION: "Service configuration error. Please contact support.",
            ErrorCategory.UNKNOWN: "An unexpected error occurred. Please try again later."
        }
        return messages.get(self.category, messages[ErrorCategory.UNKNOWN])
    
    def _get_default_error_code(self) -> str:
        """Get default error code based on category."""
        return f"{self.category.value}_{self.severity.value}"

class ErrorHandler:
    """Centralized error handling and response generation."""
    
    def __init__(self):
        self.error_counts = {}
        self.alert_thresholds = {
            ErrorSeverity.HIGH: 10,
            ErrorSeverity.CRITICAL: 5
        }
    
    async def handle_error(
        self, 
        error: Exception, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Handle an error and return a structured response.
        
        Args:
            error: The exception that occurred
            context: Additional context about the error
            
        Returns:
            Dict containing error response for the client
        """
        # Convert generic exceptions to ChatbotError
        if not isinstance(error, ChatbotError):
            error = self._classify_error(error)
        
        # Log the error
        await self._log_error(error, context)
        
        # Check for alerting
        await self._check_alerting(error)
        
        # Return structured error response
        return {
            "status": "error",
            "error_code": error.error_code,
            "message": error.user_message,
            "details": error.details,
            "timestamp": error.timestamp.isoformat(),
            "request_id": context.get("request_id") if context else None
        }
    
    def _classify_error(self, error: Exception) -> ChatbotError:
        """Classify a generic exception into a ChatbotError."""
        error_str = str(error).lower()
        
        # Rate limiting
        if any(term in error_str for term in ["rate limit", "too many requests", "quota exceeded"]):
            return ChatbotError(
                message=str(error),
                category=ErrorCategory.RATE_LIMIT,
                severity=ErrorSeverity.MEDIUM,
                error_code="rate_limit_exceeded"
            )
        
        # Timeout errors
        if any(term in error_str for term in ["timeout", "timed out", "deadline exceeded"]):
            return ChatbotError(
                message=str(error),
                category=ErrorCategory.TIMEOUT,
                severity=ErrorSeverity.MEDIUM,
                error_code="request_timeout"
            )
        
        # Database errors
        if any(term in error_str for term in ["database", "connection", "sql", "postgres"]):
            return ChatbotError(
                message=str(error),
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH,
                error_code="database_error"
            )
        
        # Network errors
        if any(term in error_str for term in ["network", "connection", "unreachable", "refused"]):
            return ChatbotError(
                message=str(error),
                category=ErrorCategory.NETWORK,
                severity=ErrorSeverity.MEDIUM,
                error_code="network_error"
            )
        
        # Authentication errors
        if any(term in error_str for term in ["auth", "unauthorized", "invalid key", "forbidden"]):
            return ChatbotError(
                message=str(error),
                category=ErrorCategory.AUTHENTICATION,
                severity=ErrorSeverity.HIGH,
                error_code="authentication_failed"
            )
        
        # Default classification
        return ChatbotError(
            message=str(error),
            category=ErrorCategory.UNKNOWN,
            severity=ErrorSeverity.MEDIUM,
            error_code="unknown_error"
        )
    
    async def _log_error(self, error: ChatbotError, context: Optional[Dict[str, Any]] = None):
        """Log the error with appropriate level and details."""
        log_data = {
            "error_code": error.error_code,
            "category": error.category.value,
            "severity": error.severity.value,
            "message": error.message,
            "details": error.details,
            "timestamp": error.timestamp.isoformat(),
            "context": context or {}
        }
        
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(f"CRITICAL ERROR: {error.message}", extra=log_data)
        elif error.severity == ErrorSeverity.HIGH:
            logger.error(f"HIGH SEVERITY ERROR: {error.message}", extra=log_data)
        elif error.severity == ErrorSeverity.MEDIUM:
            logger.warning(f"MEDIUM SEVERITY ERROR: {error.message}", extra=log_data)
        else:
            logger.info(f"LOW SEVERITY ERROR: {error.message}", extra=log_data)
    
    async def _check_alerting(self, error: ChatbotError):
        """Check if error should trigger alerts."""
        key = f"{error.category.value}_{error.severity.value}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        
        threshold = self.alert_thresholds.get(error.severity)
        if threshold and self.error_counts[key] >= threshold:
            logger.critical(
                f"ALERT: {error.severity.value.upper()} error threshold exceeded for {error.category.value}. "
                f"Count: {self.error_counts[key]}, Threshold: {threshold}"
            )
            # In production, this would trigger actual alerts (email, Slack, etc.)

# Global error handler instance
error_handler = ErrorHandler()

# Convenience functions
async def handle_websocket_error(websocket, error: Exception, context: Optional[Dict[str, Any]] = None):
    """Handle WebSocket errors and send appropriate response."""
    try:
        error_response = await error_handler.handle_error(error, context)
        await safe_send(websocket, error_response)
    except Exception as e:
        logger.critical(f"Failed to handle WebSocket error: {e}")
        # Fallback response
        await safe_send(websocket, {
            "status": "error",
            "message": "An unexpected error occurred. Please try again later.",
            "error_code": "handler_failure"
        })

async def safe_send(websocket, data: Dict[str, Any]) -> bool:
    """Safely send data through WebSocket with error handling."""
    try:
        await websocket.send_json(data)
        return True
    except Exception as e:
        logger.error(f"Failed to send WebSocket message: {e}")
        return False

# Circuit breaker pattern for external services
class CircuitBreaker:
    """Circuit breaker implementation for external service calls."""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise ChatbotError(
                    "Service temporarily unavailable due to repeated failures",
                    category=ErrorCategory.EXTERNAL_SERVICE,
                    severity=ErrorSeverity.HIGH,
                    error_code="circuit_breaker_open"
                )
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.last_failure_time:
            return True
        return (datetime.utcnow() - self.last_failure_time).seconds >= self.timeout
    
    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

# Retry mechanism with exponential backoff
async def retry_with_backoff(
    func, 
    max_retries: int = 3, 
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    *args, 
    **kwargs
):
    """Retry function with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise e
            
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
            await asyncio.sleep(delay)
