"""
Tests for input validation and sanitization.

Tests cover:
- UUID validation
- Email validation
- URL validation
- Integer validation with ranges
- String validation with constraints
- Choice validation
- List validation
- HTML sanitization
- SQL injection prevention
"""

import pytest
from rest_framework.exceptions import ValidationError
from apps.core.validators import (
    InputValidator,
    InputSanitizer,
    validate_pagination_params,
    validate_search_params,
    validate_ordering_param
)
from unittest.mock import Mock


class TestInputValidator:
    """Test InputValidator class."""

    def test_validate_uuid_valid(self):
        """Test UUID validation with valid UUID."""
        validator = InputValidator()
        valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
        result = validator.validate_uuid(valid_uuid)
        assert result == valid_uuid

    def test_validate_uuid_invalid(self):
        """Test UUID validation with invalid UUID."""
        validator = InputValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_uuid("invalid-uuid")
        assert 'Invalid UUID format' in str(exc_info.value)

    def test_validate_email_valid(self):
        """Test email validation with valid email."""
        validator = InputValidator()
        result = validator.validate_email("test@example.com")
        assert result == "test@example.com"

    def test_validate_email_invalid(self):
        """Test email validation with invalid email."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_email("invalid-email")

    def test_validate_url_valid(self):
        """Test URL validation with valid URL."""
        validator = InputValidator()
        result = validator.validate_url("https://example.com")
        assert result == "https://example.com"

    def test_validate_url_require_https(self):
        """Test URL validation with HTTPS requirement."""
        validator = InputValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_url("http://example.com", require_https=True)
        assert 'must use HTTPS' in str(exc_info.value)

    def test_validate_integer_valid(self):
        """Test integer validation."""
        validator = InputValidator()
        result = validator.validate_integer(42)
        assert result == 42

    def test_validate_integer_range(self):
        """Test integer validation with range constraints."""
        validator = InputValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_integer(150, min_value=1, max_value=100)
        assert 'must be at most 100' in str(exc_info.value)

    def test_validate_string_length(self):
        """Test string validation with length constraints."""
        validator = InputValidator()
        result = validator.validate_string("test", min_length=2, max_length=10)
        assert result == "test"

    def test_validate_string_too_long(self):
        """Test string validation with too long string."""
        validator = InputValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_string("x" * 20, max_length=10)
        assert 'must be at most 10 characters' in str(exc_info.value)

    def test_validate_choice_valid(self):
        """Test choice validation with valid choice."""
        validator = InputValidator()
        result = validator.validate_choice("active", ["active", "inactive"])
        assert result == "active"

    def test_validate_choice_invalid(self):
        """Test choice validation with invalid choice."""
        validator = InputValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_choice("invalid", ["active", "inactive"])
        assert 'must be one of' in str(exc_info.value)

    def test_validate_list_valid(self):
        """Test list validation."""
        validator = InputValidator()
        result = validator.validate_list([1, 2, 3], min_length=2, max_length=5)
        assert result == [1, 2, 3]

    def test_validate_list_too_short(self):
        """Test list validation with too few items."""
        validator = InputValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_list([1], min_length=2)
        assert 'must contain at least 2 items' in str(exc_info.value)


class TestInputSanitizer:
    """Test InputSanitizer class."""

    def test_sanitize_html_xss(self):
        """Test HTML sanitization against XSS."""
        sanitizer = InputSanitizer()
        malicious = '<script>alert("XSS")</script><p>Safe content</p>'
        result = sanitizer.sanitize_html(malicious)
        assert '<script>' not in result
        assert 'Safe content' in result

    def test_sanitize_html_strip_all(self):
        """Test HTML sanitization with strip all tags."""
        sanitizer = InputSanitizer()
        html = '<p>Test</p><strong>Bold</strong>'
        result = sanitizer.sanitize_html(html, strip_all=True)
        assert '<p>' not in result
        assert '<strong>' not in result
        assert 'TestBold' in result

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        sanitizer = InputSanitizer()
        dangerous = "../../../etc/passwd"
        result = sanitizer.sanitize_filename(dangerous)
        assert '..' not in result
        assert '/' not in result

    def test_sanitize_sql_like(self):
        """Test SQL LIKE pattern sanitization."""
        sanitizer = InputSanitizer()
        pattern = "test%_wildcard"
        result = sanitizer.sanitize_sql_like(pattern)
        assert '\\%' in result
        assert '\\_' in result

    def test_sanitize_search_query(self):
        """Test search query sanitization."""
        sanitizer = InputSanitizer()
        query = "  test query  "
        result = sanitizer.sanitize_search_query(query)
        assert result == "test query"


class TestHelperFunctions:
    """Test helper validation functions."""

    def test_validate_pagination_params(self):
        """Test pagination parameter validation."""
        request = Mock()
        request.GET = {'page': '2', 'page_size': '50'}
        result = validate_pagination_params(request)
        assert result['page'] == 2
        assert result['page_size'] == 50

    def test_validate_pagination_params_defaults(self):
        """Test pagination parameter validation with defaults."""
        request = Mock()
        request.GET = {}
        result = validate_pagination_params(request)
        assert result['page'] == 1
        assert result['page_size'] == 20

    def test_validate_pagination_params_max(self):
        """Test pagination parameter validation with max limit."""
        request = Mock()
        request.GET = {'page_size': '200'}
        result = validate_pagination_params(request)
        assert result['page_size'] == 100  # Should cap at max

    def test_validate_search_params(self):
        """Test search parameter validation."""
        request = Mock()
        request.GET = {'search': '  test search  '}
        result = validate_search_params(request)
        assert result == 'test search'

    def test_validate_ordering_param_valid(self):
        """Test ordering parameter validation with valid field."""
        request = Mock()
        request.GET = {'ordering': 'created_at'}
        result = validate_ordering_param(request, ['created_at', 'updated_at'])
        assert result == 'created_at'

    def test_validate_ordering_param_descending(self):
        """Test ordering parameter validation with descending order."""
        request = Mock()
        request.GET = {'ordering': '-created_at'}
        result = validate_ordering_param(request, ['created_at'])
        assert result == '-created_at'

    def test_validate_ordering_param_invalid(self):
        """Test ordering parameter validation with invalid field."""
        request = Mock()
        request.GET = {'ordering': 'malicious_field'}
        with pytest.raises(ValidationError) as exc_info:
            validate_ordering_param(request, ['created_at'])
        assert 'Invalid ordering field' in str(exc_info.value)
