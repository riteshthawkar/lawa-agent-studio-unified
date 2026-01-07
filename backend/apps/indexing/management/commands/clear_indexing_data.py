from django.core.management.base import BaseCommand
from apps.indexing.models import IndexingJob
from apps.sites.models import Site

class Command(BaseCommand):
    help = 'Clears all indexing data (jobs and resets site status)'

    def handle(self, *args, **options):
        # Delete all indexing jobs first
        job_count, _ = IndexingJob.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {job_count} indexing jobs'))
        
        # Delete all sites
        site_count, _ = Site.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {site_count} sites'))
