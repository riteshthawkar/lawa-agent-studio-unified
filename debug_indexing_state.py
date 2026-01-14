
import os
import django
import sys
from django.conf import settings

# Setup Django environment
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
django.setup()

from apps.sites.models import Site
from apps.indexing.models import IndexingJob

def check_indexing_state():
    print("\n--- DEBUGGING INDEXING STATE ---\n")
    
    # 1. Check Sites
    sites = Site.objects.all().order_by('-created_at')[:5]
    print(f"Found {sites.count()} sites (showing last 5):")
    for site in sites:
        print(f"Site ID: {site.id}")
        print(f"  Domain: {site.domain}")
        print(f"  Active Namespace: {site.active_namespace}")
        print(f"  Indexed Pages Count (Site): {site.indexed_pages_count}")
        print("-" * 30)
        
        # 2. Check Indexing Jobs for this site
        jobs = IndexingJob.objects.filter(site_id=site.id).order_by('-created_at')[:3]
        print(f"  Last 3 Jobs:")
        for job in jobs:
            print(f"    Job ID: {job.id}")
            print(f"    External Job ID: {job.external_job_id}")
            print(f"    Status: {job.status}")
            print(f"    Target Namespace: {job.target_namespace}")
            print(f"    Pages Indexed (Job): {job.pages_indexed}")
            print(f"    Documents Indexed (Job): {job.documents_indexed}")
            print(f"    Error: {job.error_message}")
            print("    ...")

if __name__ == '__main__':
    check_indexing_state()
