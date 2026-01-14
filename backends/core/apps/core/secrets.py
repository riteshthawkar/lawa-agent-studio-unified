"""
Secure secrets management utility.

This module provides functions to fetch secrets from various secret stores
(AWS Secrets Manager, environment variables, etc.) with fallback mechanisms.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from functools import lru_cache

logger = logging.getLogger(__name__)


class SecretNotFoundError(Exception):
    """Raised when a required secret cannot be found."""
    pass


@lru_cache(maxsize=128)
def get_secret_from_aws(secret_name: str, region_name: str = "us-east-1") -> Dict[str, Any]:
    """
    Fetch secret from AWS Secrets Manager.

    Args:
        secret_name: Name of the secret in AWS Secrets Manager
        region_name: AWS region

    Returns:
        Dictionary containing the secret data

    Raises:
        SecretNotFoundError: If secret cannot be retrieved
    """
    try:
        import boto3
        from botocore.exceptions import ClientError

        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name
        )

        get_secret_value_response = client.get_secret_value(SecretId=secret_name)

        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            return json.loads(secret)
        else:
            raise SecretNotFoundError(f"Secret {secret_name} is not a string")

    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            raise SecretNotFoundError(f"Secret {secret_name} not found in AWS")
        elif error_code == 'InvalidRequestException':
            raise SecretNotFoundError(f"Invalid request for secret {secret_name}")
        elif error_code == 'InvalidParameterException':
            raise SecretNotFoundError(f"Invalid parameter for secret {secret_name}")
        else:
            raise SecretNotFoundError(f"Error retrieving secret {secret_name}: {str(e)}")
    except ImportError:
        raise SecretNotFoundError("boto3 not installed. Install with: pip install boto3")


def get_secret(
    secret_name: str,
    default: Optional[str] = None,
    required: bool = False,
    use_aws: bool = False,
    aws_secret_name: Optional[str] = None,
    aws_key: Optional[str] = None
) -> str:
    """
    Get secret from environment or AWS Secrets Manager.

    Priority:
    1. Environment variable
    2. AWS Secrets Manager (if use_aws=True)
    3. Default value

    Args:
        secret_name: Environment variable name
        default: Default value if secret not found
        required: If True, raise error if secret not found
        use_aws: If True, try AWS Secrets Manager
        aws_secret_name: Name of secret in AWS (defaults to secret_name)
        aws_key: Key within the AWS secret JSON (defaults to secret_name)

    Returns:
        Secret value as string

    Raises:
        SecretNotFoundError: If required=True and secret not found

    Example:
        >>> db_password = get_secret('DB_PASSWORD', required=True)
        >>> jwt_secret = get_secret(
        ...     'JWT_SECRET',
        ...     use_aws=True,
        ...     aws_secret_name='lawa/prod/secrets',
        ...     aws_key='jwt_secret'
        ... )
    """
    # Try environment variable first
    value = os.getenv(secret_name)

    if value:
        return value

    # Try AWS Secrets Manager if enabled
    if use_aws:
        try:
            aws_secret_id = aws_secret_name or f"lawa/secrets/{secret_name}"
            secret_data = get_secret_from_aws(aws_secret_id)
            key = aws_key or secret_name

            if key in secret_data:
                return secret_data[key]

        except SecretNotFoundError as e:
            logger.warning(f"AWS Secrets Manager lookup failed: {e}")

    # Use default if provided
    if default is not None:
        return default

    # Raise error if required
    if required:
        raise SecretNotFoundError(
            f"Required secret '{secret_name}' not found in environment or secret store"
        )

    return ""


def validate_secrets(required_secrets: list[str]) -> Dict[str, bool]:
    """
    Validate that all required secrets are present.

    Args:
        required_secrets: List of secret names to check

    Returns:
        Dictionary mapping secret names to whether they exist

    Example:
        >>> results = validate_secrets(['SECRET_KEY', 'DB_PASSWORD'])
        >>> if not all(results.values()):
        ...     print("Missing secrets:", [k for k, v in results.items() if not v])
    """
    results = {}
    for secret in required_secrets:
        try:
            value = get_secret(secret, required=True)
            results[secret] = bool(value and value != f"your-{secret.lower()}")
        except SecretNotFoundError:
            results[secret] = False

    return results


def check_insecure_defaults() -> list[str]:
    """
    Check for insecure default values in production.

    Returns:
        List of environment variables that have insecure default values
    """
    insecure_patterns = [
        'your-',
        'change-this',
        'example',
        'test',
        'dev-only',
        'insecure',
    ]

    insecure_vars = []

    for key, value in os.environ.items():
        if key.startswith(('SECRET', 'PASSWORD', 'KEY', 'TOKEN')):
            value_lower = value.lower()
            for pattern in insecure_patterns:
                if pattern in value_lower:
                    insecure_vars.append(key)
                    break

    return insecure_vars


# Production secrets validation
REQUIRED_PRODUCTION_SECRETS = [
    'SECRET_KEY',
    'AUTH_JWT_SECRET',
    'LAWA_DB_PG_PASSWORD',
    'WEBHOOK_SIGNING_SECRET',
]


def validate_production_secrets() -> None:
    """
    Validate all production secrets are properly configured.

    Raises:
        SecretNotFoundError: If any required secret is missing or insecure
    """
    if os.getenv('DEBUG', 'False').lower() == 'true':
        logger.info("DEBUG mode enabled, skipping production secret validation")
        return

    # Check for missing secrets
    results = validate_secrets(REQUIRED_PRODUCTION_SECRETS)
    missing = [k for k, v in results.items() if not v]

    if missing:
        raise SecretNotFoundError(
            f"Missing or invalid production secrets: {', '.join(missing)}"
        )

    # Check for insecure defaults
    insecure = check_insecure_defaults()

    if insecure:
        raise SecretNotFoundError(
            f"Insecure default values detected in production: {', '.join(insecure)}"
        )

    logger.info("✓ All production secrets validated successfully")
