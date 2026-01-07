"""
Input validation and sanitization utilities.

Provides reusable validators and sanitizers for API endpoints to prevent
common security issues like XSS, SQL injection, and invalid data.
"""

import re
import bleach
from uuid import UUID
from typing import Any, Optional, List, Dict
from urllib.parse import urlparse
from django.core.validators import URLValidator, EmailValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError


# Allowed HTML tags for sanitization (very restrictive by default)
ALLOWED_TAGS = ['b', 'i', 'u', 'em', 'strong', 'a', 'p', 'br', 'ul', 'ol', 'li']
ALLOWED_ATTRIBUTES = {'a': ['href', 'title']}
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


class InputValidator:
    """Centralized input validation utilities."""

    @staticmethod
    def validate_uuid(value: Any, field_name: str = "field") -> str:
        """
        Validate and normalize UUID input.

        Args:
            value: The value to validate
            field_name: Name of the field for error messages

        Returns:
            str: Normalized UUID string

        Raises:
            ValidationError: If invalid UUID
        """
        if not value:
            raise ValidationError({field_name: f"{field_name} is required"})

        try:
            # Try to parse as UUID
            uuid_obj = UUID(str(value))
            return str(uuid_obj)
        except (ValueError, AttributeError, TypeError):
            raise ValidationError({field_name: f"Invalid UUID format for {field_name}"})

    @staticmethod
    def validate_email(value: str, field_name: str = "email") -> str:
        """
        Validate and normalize email input.

        Args:
            value: The email to validate
            field_name: Name of the field for error messages

        Returns:
            str: Normalized email (lowercase)

        Raises:
            ValidationError: If invalid email
        """
        if not value:
            raise ValidationError({field_name: f"{field_name} is required"})

        validator = EmailValidator()
        try:
            validator(value)
            return value.lower().strip()
        except DjangoValidationError:
            raise ValidationError({field_name: f"Invalid email format for {field_name}"})

    @staticmethod
    def validate_url(value: str, field_name: str = "url", require_https: bool = False) -> str:
        """
        Validate and normalize URL input.

        Args:
            value: The URL to validate
            field_name: Name of the field for error messages
            require_https: If True, only accept HTTPS URLs

        Returns:
            str: Normalized URL

        Raises:
            ValidationError: If invalid URL
        """
        if not value:
            raise ValidationError({field_name: f"{field_name} is required"})

        # Remove whitespace
        value = value.strip()

        # Validate URL format
        validator = URLValidator()
        try:
            validator(value)
        except DjangoValidationError:
            raise ValidationError({field_name: f"Invalid URL format for {field_name}"})

        # Check for HTTPS requirement
        if require_https:
            parsed = urlparse(value)
            if parsed.scheme != 'https':
                raise ValidationError({field_name: f"{field_name} must use HTTPS protocol"})

        return value

    @staticmethod
    def validate_integer(
        value: Any,
        field_name: str = "field",
        min_value: Optional[int] = None,
        max_value: Optional[int] = None
    ) -> int:
        """
        Validate integer input with optional range constraints.

        Args:
            value: The value to validate
            field_name: Name of the field for error messages
            min_value: Minimum allowed value (inclusive)
            max_value: Maximum allowed value (inclusive)

        Returns:
            int: Validated integer

        Raises:
            ValidationError: If invalid integer or out of range
        """
        if value is None:
            raise ValidationError({field_name: f"{field_name} is required"})

        try:
            int_value = int(value)
        except (ValueError, TypeError):
            raise ValidationError({field_name: f"{field_name} must be an integer"})

        if min_value is not None and int_value < min_value:
            raise ValidationError({field_name: f"{field_name} must be at least {min_value}"})

        if max_value is not None and int_value > max_value:
            raise ValidationError({field_name: f"{field_name} must be at most {max_value}"})

        return int_value

    @staticmethod
    def validate_string(
        value: Any,
        field_name: str = "field",
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        allowed_chars: Optional[str] = None
    ) -> str:
        """
        Validate string input with optional constraints.

        Args:
            value: The value to validate
            field_name: Name of the field for error messages
            min_length: Minimum string length
            max_length: Maximum string length
            pattern: Regex pattern the string must match
            allowed_chars: String of allowed characters (e.g., 'a-zA-Z0-9_')

        Returns:
            str: Validated string

        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            raise ValidationError({field_name: f"{field_name} is required"})

        str_value = str(value).strip()

        if min_length is not None and len(str_value) < min_length:
            raise ValidationError({field_name: f"{field_name} must be at least {min_length} characters"})

        if max_length is not None and len(str_value) > max_length:
            raise ValidationError({field_name: f"{field_name} must be at most {max_length} characters"})

        if pattern and not re.match(pattern, str_value):
            raise ValidationError({field_name: f"{field_name} format is invalid"})

        if allowed_chars and not re.match(f'^[{allowed_chars}]+$', str_value):
            raise ValidationError({field_name: f"{field_name} contains invalid characters"})

        return str_value

    @staticmethod
    def validate_choice(
        value: Any,
        choices: List[Any],
        field_name: str = "field"
    ) -> Any:
        """
        Validate that value is one of the allowed choices.

        Args:
            value: The value to validate
            choices: List of allowed values
            field_name: Name of the field for error messages

        Returns:
            The validated value

        Raises:
            ValidationError: If value not in choices
        """
        if value not in choices:
            raise ValidationError({
                field_name: f"{field_name} must be one of: {', '.join(map(str, choices))}"
            })

        return value

    @staticmethod
    def validate_list(
        value: Any,
        field_name: str = "field",
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        item_validator: Optional[callable] = None
    ) -> List:
        """
        Validate list input with optional constraints.

        Args:
            value: The value to validate
            field_name: Name of the field for error messages
            min_length: Minimum list length
            max_length: Maximum list length
            item_validator: Optional function to validate each item

        Returns:
            list: Validated list

        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(value, (list, tuple)):
            raise ValidationError({field_name: f"{field_name} must be a list"})

        list_value = list(value)

        if min_length is not None and len(list_value) < min_length:
            raise ValidationError({field_name: f"{field_name} must contain at least {min_length} items"})

        if max_length is not None and len(list_value) > max_length:
            raise ValidationError({field_name: f"{field_name} must contain at most {max_length} items"})

        if item_validator:
            validated_items = []
            for i, item in enumerate(list_value):
                try:
                    validated_items.append(item_validator(item))
                except ValidationError as e:
                    raise ValidationError({field_name: f"{field_name}[{i}]: {str(e)}"})
            return validated_items

        return list_value


class InputSanitizer:
    """Centralized input sanitization utilities."""

    @staticmethod
    def sanitize_html(value: str, strip_all: bool = False) -> str:
        """
        Sanitize HTML input to prevent XSS attacks.

        Args:
            value: The HTML string to sanitize
            strip_all: If True, strip all HTML tags

        Returns:
            str: Sanitized HTML string
        """
        if not value:
            return ""

        if strip_all:
            return bleach.clean(value, tags=[], strip=True)

        return bleach.clean(
            value,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            protocols=ALLOWED_PROTOCOLS,
            strip=True
        )

    @staticmethod
    def sanitize_filename(value: str, max_length: int = 255) -> str:
        """
        Sanitize filename to prevent directory traversal and other attacks.

        Args:
            value: The filename to sanitize
            max_length: Maximum filename length

        Returns:
            str: Sanitized filename
        """
        if not value:
            return ""

        # Remove path separators and special characters
        sanitized = re.sub(r'[^\w\s\-\.]', '', value)
        sanitized = re.sub(r'[\s]+', '_', sanitized)

        # Remove leading dots and slashes
        sanitized = sanitized.lstrip('./\\')

        # Truncate to max length
        if len(sanitized) > max_length:
            name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
            if ext:
                max_name_length = max_length - len(ext) - 1
                sanitized = f"{name[:max_name_length]}.{ext}"
            else:
                sanitized = sanitized[:max_length]

        return sanitized

    @staticmethod
    def sanitize_sql_like(value: str) -> str:
        """
        Escape special characters in SQL LIKE patterns.

        Args:
            value: The string to escape

        Returns:
            str: Escaped string safe for SQL LIKE
        """
        if not value:
            return ""

        # Escape special LIKE wildcards
        return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    @staticmethod
    def sanitize_search_query(value: str, max_length: int = 200) -> str:
        """
        Sanitize search query input.

        Args:
            value: The search query to sanitize
            max_length: Maximum query length

        Returns:
            str: Sanitized search query
        """
        if not value:
            return ""

        # Strip whitespace and limit length
        sanitized = value.strip()[:max_length]

        # Remove control characters
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32)

        return sanitized


# Convenience functions for common validation scenarios
def validate_pagination_params(request) -> Dict[str, int]:
    """
    Validate and extract pagination parameters from request.

    Args:
        request: Django/DRF request object

    Returns:
        dict: {'page': int, 'page_size': int}
    """
    validator = InputValidator()

    page = validator.validate_integer(
        request.GET.get('page', 1),
        field_name='page',
        min_value=1,
        max_value=10000
    )

    page_size = validator.validate_integer(
        request.GET.get('page_size', 20),
        field_name='page_size',
        min_value=1,
        max_value=100
    )

    return {'page': page, 'page_size': page_size}


def validate_search_params(request) -> str:
    """
    Validate and sanitize search query from request.

    Args:
        request: Django/DRF request object

    Returns:
        str: Sanitized search query
    """
    search = request.GET.get('search', '')
    if search:
        return InputSanitizer.sanitize_search_query(search)
    return ''


def validate_ordering_param(request, allowed_fields: List[str], default: str = '-created_at') -> str:
    """
    Validate ordering parameter against allowed fields.

    Args:
        request: Django/DRF request object
        allowed_fields: List of allowed field names for ordering
        default: Default ordering if not provided

    Returns:
        str: Validated ordering parameter

    Raises:
        ValidationError: If ordering field not allowed
    """
    ordering = request.GET.get('ordering', default)

    # Remove leading dash for descending order
    field = ordering.lstrip('-')

    if field not in allowed_fields:
        raise ValidationError({
            'ordering': f"Invalid ordering field. Allowed fields: {', '.join(allowed_fields)}"
        })

    return ordering
