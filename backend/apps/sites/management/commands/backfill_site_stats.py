"""
Management command to backfill Site statistics from completed IndexingJobs.

This is needed for sites that were indexed before the stats update fix was deployed.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.sites.models import Site
from apps.indexing.models import IndexingJob


class Command(BaseCommand):
    help = 'Backfill Site statistics from completed IndexingJobs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--site-id',
            type=str,
            help='Specific site ID to update (optional)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        site_id = options.get('site_id')
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))

        # Get sites to update
        if site_id:
            sites = Site.objects.filter(id=site_id)
        else:
            # Only update sites with 0 stats
            sites = Site.objects.filter(indexed_pages_count=0)

        updated_count = 0
        for site in sites:
            # Get the last completed indexing job for this site
            last_completed_job = IndexingJob.objects.filter(
                site_id=site.id,
                status='completed'
            ).order_by('-completed_at').first()

            if last_completed_job and last_completed_job.documents_indexed > 0:
                self.stdout.write(
                    f"Site {site.id} ({site.domain}): "
                    f"documents_indexed={last_completed_job.documents_indexed}"
                )

                if not dry_run:
                    site.indexed_pages_count = last_completed_job.documents_indexed
                    site.total_documents = last_completed_job.documents_indexed
                    if not site.last_indexed_at and last_completed_job.completed_at:
                        site.last_indexed_at = last_completed_job.completed_at
                    site.save(update_fields=[
                        'indexed_pages_count',
                        'total_documents',
                        'last_indexed_at'
                    ])
                    updated_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  Updated!"))
                else:
                    self.stdout.write(self.style.WARNING(f"  Would update"))
            else:
                self.stdout.write(
                    f"Site {site.id} ({site.domain}): No completed job with documents"
                )

        if dry_run:
            self.stdout.write(self.style.WARNING(f'\nDry run complete. {updated_count} sites would be updated.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\nBackfill complete. {updated_count} sites updated.'))
