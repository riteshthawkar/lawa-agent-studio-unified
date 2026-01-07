import hmac
import hashlib
import json
from rest_framework import status as http_status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from django.utils import timezone
from .models import WebhookEvent, AuditLog
from apps.indexing.models import IndexingJob
from apps.indexing.services import IndexingService
from apps.core.views import BaseViewSet
from apps.core.exceptions import InvalidWebhookSignature


class WebhookViewSet(BaseViewSet):
    """Webhook management"""
    queryset = WebhookEvent.objects.all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter webhook events by organization"""
        queryset = super().get_queryset()
        request = self.request
        
        if hasattr(request, 'org_id') and request.org_id:
            return queryset.filter(org_id=request.org_id)
        
        return queryset.none()


@api_view(['POST'])
@authentication_classes([])  # Bypass default authentication for webhooks
@permission_classes([AllowAny])
def indexing_webhook(request):
    """Handle indexing service webhooks according to API specification"""
    try:
        # Verify webhook signature
        if not verify_webhook_signature(request):
            raise InvalidWebhookSignature("Invalid webhook signature")
        
        # Parse webhook payload according to API spec
        payload = request.data
        external_job_id = payload.get('external_job_id')
        task_id = payload.get('task_id')
        job_status = payload.get('status')

        if not external_job_id or not job_status:
            return Response(
                {'error': 'Missing required fields: external_job_id and status'},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        # Check if this is a progress update (intermediate) or completion webhook
        is_progress_update = payload.get('is_progress_update', False)

        # Extract result data according to API spec
        result = payload.get('result', {})
        phase1_result = result.get('phase1_result') if result else None
        phase2_result = result.get('phase2_result') if result else None
        error_message = payload.get('error')

        # Bug #26 fix: Extract per-URL results for visibility
        url_results = None
        if phase2_result and isinstance(phase2_result, dict):
            url_results = phase2_result.get('url_results', [])

        # Extract progress data - check multiple sources
        progress_data = None

        # First, check for direct progress payload (from progress webhooks)
        if payload.get('progress'):
            progress = payload.get('progress', {})
            progress_data = {
                'urls_collected': progress.get('urls_collected', 0),
                'urls_processed': progress.get('urls_processed', 0),
                'documents_indexed': progress.get('documents_indexed', 0)
            }
        # Then check result.stats (from completion webhooks)
        elif result and result.get('stats'):
            stats = result.get('stats', {})
            progress_data = {
                'urls_collected': stats.get('total_urls_collected', stats.get('urls_collected', 0)),
                'urls_processed': stats.get('total_urls_processed', stats.get('urls_processed', 0)),
                'documents_indexed': stats.get('total_documents_indexed', stats.get('documents_indexed', 0))
            }
        # Finally, fallback to phase1_result.stats for legacy compatibility
        elif phase1_result and isinstance(phase1_result, dict):
            stats = phase1_result.get('stats', {})
            progress_data = {
                'urls_collected': stats.get('urls_collected', 0),
                'urls_processed': stats.get('urls_processed', 0),
                'documents_indexed': stats.get('documents_indexed', 0)
            }
        
        # Update indexing job
        indexing_service = IndexingService()
        job = indexing_service.update_job_status(
            job_id=external_job_id,
            status=job_status,
            phase1_result=phase1_result,
            phase2_result=phase2_result,
            error_message=error_message,
            progress_data=progress_data,
            url_results=url_results  # Bug #26 fix: Pass URL results for storage
        )

        # Zero-Downtime Re-indexing Logic (Bug #7 fix: consolidated Site status updates)
        # Note: Site status (active/indexing) is now managed by IndexingService._update_site_stats()
        # Here we only handle namespace switching and cleanup
        if job_status == 'completed' and job.target_namespace:
            from apps.sites.models import Site
            from apps.background_jobs.models import OutboxEvent
            try:
                site = Site.objects.get(id=job.site_id)
                old_namespace = site.active_namespace

                # Activate new namespace
                site.active_namespace = job.target_namespace
                site.save(update_fields=['active_namespace'])

                # Bug #9 fix: Schedule namespace cleanup as background job
                if old_namespace and old_namespace != job.target_namespace:
                    # Create outbox event for namespace cleanup
                    OutboxEvent.objects.create(
                        event_type='cleanup_namespace',
                        payload={
                            'namespace': old_namespace,
                            'site_id': str(job.site_id),
                            'replaced_by': job.target_namespace
                        },
                        status='pending'
                    )
            except Site.DoesNotExist:
                pass
        
        # Note: IndexingJob doesn't track per-webhook delivery status in MVP
        # Delivery success is reflected via WebhookEvent below
        
        # Log webhook event
        WebhookEvent.objects.create(
            kind='indexing_update',
            target_url=request.build_absolute_uri(),
            payload=payload,
            result_status=200
        )
        
        # Create audit log
        AuditLog.objects.create(
            org_id=job.org_id,
            action='indexing_job_updated',
            target_type='IndexingJob',
            target_id=job.id,
            details={
                'status': job_status,
                'external_job_id': external_job_id,
                'task_id': task_id,
                'webhook_source': 'indexing_service'
            }
        )

        return Response({'status': 'success'})

    except InvalidWebhookSignature as e:
        return Response(
            {'error': str(e)},
            status=http_status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Webhook processing failed: {e}")

        # Log failed webhook
        webhook_event = WebhookEvent.objects.create(
            kind='indexing_update',
            target_url=request.build_absolute_uri(),
            payload=request.data,
            result_status=500,
            attempts=1,
            last_attempt_at=timezone.now()
        )

        # Bug #8 fix: Queue for retry via outbox pattern
        from apps.background_jobs.models import OutboxEvent
        OutboxEvent.objects.create(
            event_type='retry_webhook_processing',
            payload={
                'webhook_event_id': str(webhook_event.id),
                'original_payload': request.data,
                'error': str(e)
            },
            status='pending'
        )

        return Response(
            {'error': 'Webhook processing failed, queued for retry'},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def verify_webhook_signature(request):
    """
    Verify webhook HMAC signature.

    Security behavior:
    - If WEBHOOK_SIGNING_SECRET is configured: requires valid signature
    - If WEBHOOK_SIGNING_SECRET is not configured: allows unsigned requests (dev mode)
    - Logs warnings for security-related events
    """
    import logging
    logger = logging.getLogger(__name__)

    # Get the signing secret from settings (may be None or empty)
    webhook_secret = getattr(settings, 'WEBHOOK_SIGNING_SECRET', None)

    # If no secret is configured, allow unsigned webhooks (development mode)
    if not webhook_secret:
        logger.warning(
            "WEBHOOK_SIGNING_SECRET not configured - webhook signature verification disabled. "
            "This is insecure for production!"
        )
        return True

    # Get signature from request headers
    signature = request.META.get('HTTP_X_SIGNATURE')

    # If secret is configured but no signature provided, reject
    if not signature:
        logger.warning("Webhook rejected: signature required but not provided")
        return False

    # Get the raw body
    body = request.body

    # Create expected signature
    try:
        expected_signature = hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
    except Exception as e:
        logger.error(f"Error creating webhook signature: {e}")
        return False

    # Compare signatures securely
    is_valid = hmac.compare_digest(signature, expected_signature)

    if not is_valid:
        logger.warning("Webhook rejected: invalid signature")

    return is_valid


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit_logs(request, org_id):
    """Get audit logs for organization"""
    # Verify organization access
    if hasattr(request, 'org_id') and str(org_id) != str(request.org_id):
        return Response(
            {'error': 'Organization access denied'},
            status=http_status.HTTP_403_FORBIDDEN
        )
    
    logs = AuditLog.objects.filter(org_id=org_id).order_by('-created_at')[:100]
    
    return Response([{
        'id': str(log.id),
        'action': log.action,
        'target_type': log.target_type,
        'target_id': str(log.target_id),
        'actor_user_id': str(log.actor_user_id) if log.actor_user_id else None,
        'details': log.details,
        'created_at': log.created_at
    } for log in logs])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def retry_webhook(request, webhook_id):
    """Retry failed webhook delivery"""
    try:
        webhook = WebhookEvent.objects.get(id=webhook_id)

        # Check organization access
        if hasattr(request, 'org_id') and str(webhook.org_id) != str(request.org_id):
            return Response(
                {'error': 'Webhook not found'},
                status=http_status.HTTP_404_NOT_FOUND
            )

        # Reset webhook for retry
        webhook.result_status = None  # Reset status
        webhook.attempts = 0
        webhook.last_attempt_at = None
        webhook.save()

        return Response({'status': 'Webhook queued for retry'})

    except WebhookEvent.DoesNotExist:
        return Response(
            {'error': 'Webhook not found'},
            status=http_status.HTTP_404_NOT_FOUND
        )
