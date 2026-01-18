#!/usr/bin/env python
"""
Cleanup script to delete orphaned organizations.
An orphaned organization is one that has no memberships (no users linked to it).

Run: python3 cleanup_orphaned_orgs.py
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from apps.organizations.models import Organization, Membership
from django.db import transaction
from django.db.models import Count

def cleanup():
    print("=" * 60)
    print("ORPHANED ORGANIZATIONS CLEANUP")
    print("=" * 60)
    
    # Find organizations with no memberships
    orphaned_orgs = Organization.objects.annotate(
        member_count=Count('memberships')
    ).filter(member_count=0)
    
    orphan_count = orphaned_orgs.count()
    
    if orphan_count == 0:
        print("\n✅ No orphaned organizations found. Database is clean.")
        return
    
    print(f"\n⚠️  Found {orphan_count} orphaned organizations")
    print("-" * 50)
    
    # Show first 10 for confirmation
    for org in orphaned_orgs[:10]:
        print(f"  - {org.name} (slug: {org.slug})")
    if orphan_count > 10:
        print(f"  ... and {orphan_count - 10} more")
    
    print("-" * 50)
    print(f"\n🗑️  Deleting {orphan_count} orphaned organizations...")
    
    # Delete orphaned organizations
    with transaction.atomic():
        # Get IDs first since the queryset might change during deletion
        orphan_ids = list(orphaned_orgs.values_list('id', flat=True))
        deleted_count, _ = Organization.objects.filter(id__in=orphan_ids).delete()
    
    print(f"✅ Deleted {deleted_count} orphaned organizations")
    
    # Verify
    remaining_orphans = Organization.objects.annotate(
        member_count=Count('memberships')
    ).filter(member_count=0).count()
    
    print(f"\n📊 Post-cleanup verification:")
    print(f"  Remaining orphaned orgs: {remaining_orphans}")
    print(f"  Total organizations: {Organization.objects.count()}")

if __name__ == '__main__':
    cleanup()
