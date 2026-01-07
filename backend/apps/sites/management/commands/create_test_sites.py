#!/usr/bin/env python3
"""
Django management command to create test sites for the indexing backend.
"""

from django.core.management.base import BaseCommand
from apps.sites.models import Site


class Command(BaseCommand):
    help = 'Create test sites for indexing backend testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domains',
            nargs='+',
            default=['example.com', 'test.com', 'demo.org'],
            help='List of domains to create as test sites'
        )

    def handle(self, *args, **options):
        domains = options['domains']
        
        self.stdout.write('Creating test sites...')
        
        created_count = 0
        for domain in domains:
            site, created = Site.objects.get_or_create(
                domain=domain,
                defaults={
                    'status': 'active'
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Created site: {domain} (ID: {site.id})')
                )
                created_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠️ Site already exists: {domain} (ID: {site.id})')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'\n🎉 Created {created_count} new test sites')
        )
        
        # List all sites
        self.stdout.write('\n📋 All sites in database:')
        for site in Site.objects.all():
            self.stdout.write(f'  - {site.domain} (ID: {site.id}, Status: {site.status})')
