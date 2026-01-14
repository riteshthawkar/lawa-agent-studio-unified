"""
Django management command to retry failed webhooks.

Usage:
    python manage.py retry_webhooks
    python manage.py retry_webhooks --limit 50
    python manage.py retry_webhooks --webhook-id <uuid>
"""

from django.core.management.base import BaseCommand
from apps.webhooks.retry_service import WebhookRetryService, retry_webhook_by_id


class Command(BaseCommand):
    help = 'Retry failed webhook deliveries with exponential backoff'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Maximum number of webhooks to process (default: 100)'
        )
        parser.add_argument(
            '--webhook-id',
            type=str,
            help='Retry a specific webhook by ID'
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Display webhook statistics'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        webhook_id = options.get('webhook_id')
        show_stats = options.get('stats', False)

        # Show stats if requested
        if show_stats:
            self.stdout.write(self.style.SUCCESS('\nWebhook Statistics:'))
            stats = WebhookRetryService.get_webhook_stats()
            for key, value in stats.items():
                self.stdout.write(f"  {key}: {value}")
            return

        # Retry specific webhook
        if webhook_id:
            self.stdout.write(f'Retrying webhook {webhook_id}...')
            success = retry_webhook_by_id(webhook_id)
            if success:
                self.stdout.write(self.style.SUCCESS(f'Successfully delivered webhook {webhook_id}'))
            else:
                self.stdout.write(self.style.ERROR(f'Failed to deliver webhook {webhook_id}'))
            return

        # Batch retry failed webhooks
        self.stdout.write(f'Processing up to {limit} failed webhooks...')
        stats = WebhookRetryService.retry_failed_webhooks(limit=limit)

        self.stdout.write(self.style.SUCCESS(f'\nRetry batch complete:'))
        self.stdout.write(f"  Processed: {stats['processed']}")
        self.stdout.write(self.style.SUCCESS(f"  Succeeded: {stats['succeeded']}"))
        self.stdout.write(self.style.ERROR(f"  Failed: {stats['failed']}"))
        self.stdout.write(self.style.WARNING(f"  Skipped: {stats['skipped']}"))
