"""
Webhook retry service with exponential backoff.

Provides reliable webhook delivery with:
- Exponential backoff retry strategy
- Configurable max attempts
- Failure tracking and logging
- Batch retry processing
"""

import logging
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from django.utils import timezone
from django.conf import settings
from .models import WebhookEvent

logger = logging.getLogger(__name__)


class WebhookRetryService:
    """
    Service for managing webhook delivery with exponential backoff retry.

    Retry Strategy:
    - Attempt 1: Immediate
    - Attempt 2: 1 minute later
    - Attempt 3: 5 minutes later
    - Attempt 4: 15 minutes later
    - Attempt 5: 1 hour later
    - Attempt 6: 4 hours later
    - Attempt 7: 12 hours later
    - Attempt 8+: 24 hours later (max)
    """

    # Configuration
    MAX_ATTEMPTS = 10
    BASE_DELAY = 60  # 1 minute in seconds
    MAX_DELAY = 86400  # 24 hours in seconds
    REQUEST_TIMEOUT = 30  # seconds
    EXPONENTIAL_BASE = 2

    # HTTP Status codes that should NOT be retried
    NO_RETRY_STATUS_CODES = {
        400,  # Bad Request
        401,  # Unauthorized
        403,  # Forbidden
        404,  # Not Found
        405,  # Method Not Allowed
        410,  # Gone
        422,  # Unprocessable Entity
    }

    @classmethod
    def calculate_next_retry_delay(cls, attempt_number: int) -> int:
        """
        Calculate exponential backoff delay in seconds.

        Args:
            attempt_number: Current attempt number (1-indexed)

        Returns:
            int: Delay in seconds before next retry
        """
        if attempt_number <= 0:
            return 0

        # Exponential backoff: delay = base_delay * (exponential_base ^ (attempt - 1))
        delay = cls.BASE_DELAY * (cls.EXPONENTIAL_BASE ** (attempt_number - 1))

        # Cap at maximum delay
        return min(delay, cls.MAX_DELAY)

    @classmethod
    def get_next_retry_time(cls, webhook_event: WebhookEvent) -> Optional[datetime]:
        """
        Calculate when the next retry should occur.

        Args:
            webhook_event: WebhookEvent instance

        Returns:
            datetime: Next retry time, or None if max attempts reached
        """
        if webhook_event.attempts >= cls.MAX_ATTEMPTS:
            return None

        delay = cls.calculate_next_retry_delay(webhook_event.attempts + 1)
        base_time = webhook_event.last_attempt_at or webhook_event.created_at

        return base_time + timedelta(seconds=delay)

    @classmethod
    def should_retry(cls, webhook_event: WebhookEvent) -> bool:
        """
        Determine if webhook should be retried.

        Args:
            webhook_event: WebhookEvent instance

        Returns:
            bool: True if should retry, False otherwise
        """
        # Check if max attempts reached
        if webhook_event.attempts >= cls.MAX_ATTEMPTS:
            logger.info(
                f"Webhook {webhook_event.id} reached max attempts ({cls.MAX_ATTEMPTS})",
                extra={'webhook_id': str(webhook_event.id)}
            )
            return False

        # Check if status code indicates permanent failure
        if webhook_event.result_status in cls.NO_RETRY_STATUS_CODES:
            logger.info(
                f"Webhook {webhook_event.id} received non-retryable status {webhook_event.result_status}",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'status_code': webhook_event.result_status
                }
            )
            return False

        # Check if it's time for next retry
        next_retry_time = cls.get_next_retry_time(webhook_event)
        if next_retry_time and timezone.now() < next_retry_time:
            logger.debug(
                f"Webhook {webhook_event.id} not ready for retry (next: {next_retry_time})",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'next_retry': next_retry_time.isoformat()
                }
            )
            return False

        return True

    @classmethod
    def send_webhook(cls, webhook_event: WebhookEvent) -> bool:
        """
        Attempt to send a webhook.

        Args:
            webhook_event: WebhookEvent instance

        Returns:
            bool: True if successful, False otherwise
        """
        webhook_event.attempts += 1
        webhook_event.last_attempt_at = timezone.now()

        try:
            logger.info(
                f"Sending webhook {webhook_event.id} (attempt {webhook_event.attempts}/{cls.MAX_ATTEMPTS})",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'attempt': webhook_event.attempts,
                    'kind': webhook_event.kind,
                    'target_url': webhook_event.target_url
                }
            )

            # Send HTTP POST request
            response = requests.post(
                webhook_event.target_url,
                json=webhook_event.payload,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Lawa-Webhook/1.0',
                    'X-Webhook-Event': webhook_event.kind,
                    'X-Webhook-Attempt': str(webhook_event.attempts),
                },
                timeout=cls.REQUEST_TIMEOUT
            )

            webhook_event.result_status = response.status_code

            # Success if 2xx status code
            if 200 <= response.status_code < 300:
                webhook_event.save()
                logger.info(
                    f"Webhook {webhook_event.id} delivered successfully",
                    extra={
                        'webhook_id': str(webhook_event.id),
                        'status_code': response.status_code,
                        'attempt': webhook_event.attempts
                    }
                )
                return True

            # Log failure
            logger.warning(
                f"Webhook {webhook_event.id} failed with status {response.status_code}",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'status_code': response.status_code,
                    'attempt': webhook_event.attempts,
                    'response_body': response.text[:500]  # Log first 500 chars
                }
            )

        except requests.exceptions.Timeout:
            logger.warning(
                f"Webhook {webhook_event.id} timed out after {cls.REQUEST_TIMEOUT}s",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'attempt': webhook_event.attempts
                }
            )
            webhook_event.result_status = 408  # Request Timeout

        except requests.exceptions.ConnectionError as e:
            logger.warning(
                f"Webhook {webhook_event.id} connection error: {str(e)}",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'attempt': webhook_event.attempts,
                    'error': str(e)
                }
            )
            webhook_event.result_status = 503  # Service Unavailable

        except Exception as e:
            logger.error(
                f"Webhook {webhook_event.id} unexpected error: {str(e)}",
                extra={
                    'webhook_id': str(webhook_event.id),
                    'attempt': webhook_event.attempts,
                    'error': str(e)
                },
                exc_info=True
            )
            webhook_event.result_status = 500  # Internal Server Error

        finally:
            webhook_event.save()

        return False

    @classmethod
    def retry_failed_webhooks(cls, limit: int = 100) -> Dict[str, int]:
        """
        Batch process failed webhooks that are ready for retry.

        Args:
            limit: Maximum number of webhooks to process in one batch

        Returns:
            dict: Statistics about the retry operation
        """
        logger.info(f"Starting webhook retry batch (limit={limit})")

        stats = {
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'skipped': 0,
        }

        # Find failed webhooks ready for retry
        # result_status != 2xx or result_status is None
        failed_webhooks = WebhookEvent.objects.filter(
            result_status__isnull=False
        ).exclude(
            result_status__gte=200,
            result_status__lt=300
        ).order_by('last_attempt_at')[:limit]

        for webhook in failed_webhooks:
            stats['processed'] += 1

            if not cls.should_retry(webhook):
                stats['skipped'] += 1
                continue

            success = cls.send_webhook(webhook)

            if success:
                stats['succeeded'] += 1
            else:
                stats['failed'] += 1

        logger.info(
            f"Webhook retry batch complete: {stats}",
            extra=stats
        )

        return stats

    @classmethod
    def create_and_send_webhook(
        cls,
        kind: str,
        target_url: str,
        payload: dict
    ) -> WebhookEvent:
        """
        Create a new webhook event and attempt immediate delivery.

        Args:
            kind: Type of webhook event
            target_url: Target URL for webhook
            payload: JSON payload to send

        Returns:
            WebhookEvent: Created webhook event instance
        """
        webhook = WebhookEvent.objects.create(
            kind=kind,
            target_url=target_url,
            payload=payload
        )

        logger.info(
            f"Created webhook {webhook.id} for {kind}",
            extra={
                'webhook_id': str(webhook.id),
                'kind': kind,
                'target_url': target_url
            }
        )

        # Attempt immediate delivery
        cls.send_webhook(webhook)

        return webhook

    @classmethod
    def get_webhook_stats(cls) -> Dict[str, int]:
        """
        Get statistics about webhook delivery.

        Returns:
            dict: Webhook statistics
        """
        total = WebhookEvent.objects.count()
        successful = WebhookEvent.objects.filter(
            result_status__gte=200,
            result_status__lt=300
        ).count()
        failed = WebhookEvent.objects.exclude(
            result_status__gte=200,
            result_status__lt=300
        ).filter(
            result_status__isnull=False
        ).count()
        pending = WebhookEvent.objects.filter(
            result_status__isnull=True
        ).count()
        max_attempts_reached = WebhookEvent.objects.filter(
            attempts__gte=cls.MAX_ATTEMPTS
        ).exclude(
            result_status__gte=200,
            result_status__lt=300
        ).count()

        return {
            'total': total,
            'successful': successful,
            'failed': failed,
            'pending': pending,
            'max_attempts_reached': max_attempts_reached,
            'success_rate': (successful / total * 100) if total > 0 else 0,
        }


# Celery task for periodic webhook retry (if Celery is configured)
try:
    from celery import shared_task

    @shared_task
    def retry_failed_webhooks_task(limit=100):
        """
        Celery task to retry failed webhooks.

        Can be scheduled to run periodically (e.g., every 5 minutes).
        """
        return WebhookRetryService.retry_failed_webhooks(limit=limit)

except ImportError:
    # Celery not installed
    logger.info("Celery not available, webhook retry task not registered")
    pass


# Helper function for manual retry
def retry_webhook_by_id(webhook_id: str) -> bool:
    """
    Manually retry a specific webhook by ID.

    Args:
        webhook_id: UUID of the webhook event

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        webhook = WebhookEvent.objects.get(id=webhook_id)
        return WebhookRetryService.send_webhook(webhook)
    except WebhookEvent.DoesNotExist:
        logger.error(f"Webhook {webhook_id} not found")
        return False
