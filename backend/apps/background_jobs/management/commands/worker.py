import time
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.background_jobs.models import OutboxEvent
from apps.webhooks.models import WebhookEvent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Background worker for processing outbox events'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Polling interval in seconds (default: 5)'
        )
        parser.add_argument(
            '--max-attempts',
            type=int,
            default=3,
            help='Maximum retry attempts (default: 3)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        max_attempts = options['max_attempts']
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting background worker (interval: {interval}s)')
        )
        
        while True:
            try:
                self.process_outbox_events(max_attempts)
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('Worker stopped by user'))
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(interval)

    def process_outbox_events(self, max_attempts):
        """Process pending outbox events"""
        with transaction.atomic():
            # Get pending events using SELECT FOR UPDATE SKIP LOCKED
            events = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
                status='pending',
                attempts__lt=max_attempts
            ).order_by('created_at')[:10]
            
            for event in events:
                try:
                    self.process_event(event)
                except Exception as e:
                    logger.error(f"Failed to process event {event.id}: {e}")
                    event.attempts += 1
                    event.last_attempt_at = timezone.now()
                    if event.attempts >= max_attempts:
                        event.status = 'failed'
                        event.error_message = str(e)
                    event.save()

    def process_event(self, event):
        """Process a single outbox event"""
        event.status = 'processing'
        event.attempts += 1
        event.last_attempt_at = timezone.now()
        event.save()
        
        try:
            if event.event_type == 'deliver_webhook':
                self.deliver_webhook(event)
            elif event.event_type == 'send_email':
                self.send_email(event)
            elif event.event_type == 'rollup_usage':
                self.rollup_usage(event)
            else:
                logger.warning(f"Unknown event type: {event.event_type}")
                event.status = 'failed'
                event.error_message = f"Unknown event type: {event.event_type}"
                return
            
            event.status = 'completed'
            event.save()
            logger.info(f"Successfully processed event {event.id}")
            
        except Exception as e:
            event.status = 'failed'
            event.error_message = str(e)
            event.save()
            raise

    def deliver_webhook(self, event):
        """Deliver webhook to target URL"""
        import requests
        
        payload = event.payload
        target_url = payload.get('target_url')
        webhook_data = payload.get('data', {})
        
        if not target_url:
            raise ValueError("Missing target_url in webhook payload")
        
        # Create webhook event record
        webhook_event = WebhookEvent.objects.create(
            kind='indexing_update',
            target_url=target_url,
            payload=webhook_data
        )
        
        try:
            response = requests.post(
                target_url,
                json=webhook_data,
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            
            webhook_event.result_status = response.status_code
            webhook_event.attempts = 1
            webhook_event.last_attempt_at = timezone.now()
            webhook_event.save()
            
            response.raise_for_status()
            
        except Exception as e:
            webhook_event.result_status = getattr(e, 'response', {}).get('status_code', 0)
            webhook_event.attempts = 1
            webhook_event.last_attempt_at = timezone.now()
            webhook_event.save()
            raise

    def send_email(self, event):
        """Send email notification using Django's email backend"""
        from django.core.mail import send_mail
        from django.conf import settings

        payload = event.payload
        to_email = payload.get('to')
        subject = payload.get('subject')
        body = payload.get('body')
        html_body = payload.get('html_body')
        from_email = payload.get('from_email', settings.DEFAULT_FROM_EMAIL)

        if not to_email or not subject:
            raise ValueError("Missing required email fields: 'to' and 'subject'")

        # Ensure to_email is a list
        if isinstance(to_email, str):
            to_email = [to_email]

        try:
            send_mail(
                subject=subject,
                message=body or '',
                from_email=from_email,
                recipient_list=to_email,
                html_message=html_body,
                fail_silently=False
            )
            logger.info(f"Email sent successfully to {to_email}")

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            raise

    def rollup_usage(self, event):
        """Rollup usage statistics for billing period"""
        from apps.usage.models import UsageEvent, Quota
        from django.db.models import Sum, Count
        from datetime import datetime, timedelta

        payload = event.payload
        org_id = payload.get('org_id')
        period_start = payload.get('period_start')
        period_end = payload.get('period_end')

        if not org_id:
            raise ValueError("Missing required field: 'org_id'")

        try:
            # Parse dates if provided as strings
            if period_start and isinstance(period_start, str):
                period_start = datetime.fromisoformat(period_start.replace('Z', '+00:00'))
            if period_end and isinstance(period_end, str):
                period_end = datetime.fromisoformat(period_end.replace('Z', '+00:00'))

            # Default to current month if not specified
            if not period_start:
                now = timezone.now()
                period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if not period_end:
                # End of current month
                next_month = period_start.replace(day=28) + timedelta(days=4)
                period_end = next_month.replace(day=1) - timedelta(seconds=1)

            # Aggregate usage events for the period
            usage_aggregation = UsageEvent.objects.filter(
                org_id=org_id,
                occurred_at__gte=period_start,
                occurred_at__lte=period_end
            ).values('type').annotate(
                total_units=Sum('units'),
                total_cost_cents=Sum('cost_cents'),
                event_count=Count('id')
            )

            # Build usage summary
            usage_summary = {}
            total_cost_cents = 0
            for agg in usage_aggregation:
                usage_summary[agg['type']] = {
                    'units': agg['total_units'] or 0,
                    'cost_cents': agg['total_cost_cents'] or 0,
                    'count': agg['event_count']
                }
                total_cost_cents += agg['total_cost_cents'] or 0

            # Update or create quota with usage summary
            quota, created = Quota.objects.update_or_create(
                org_id=org_id,
                period_start=period_start,
                period_end=period_end,
                defaults={
                    'usage': {
                        'by_type': usage_summary,
                        'total_cost_cents': total_cost_cents,
                        'last_rollup': timezone.now().isoformat()
                    }
                }
            )

            logger.info(
                f"Usage rollup completed for org {org_id}: "
                f"period {period_start.date()} to {period_end.date()}, "
                f"total cost: ${total_cost_cents / 100:.2f}"
            )

        except Exception as e:
            logger.error(f"Failed to rollup usage for org {org_id}: {e}")
            raise
