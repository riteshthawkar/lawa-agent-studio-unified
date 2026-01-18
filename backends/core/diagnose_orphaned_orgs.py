#!/usr/bin/env python
"""
Diagnostic script to identify orphaned organizations.
An orphaned organization is one that has no memberships (no users linked to it).

Run: python manage.py shell < diagnose_orphaned_orgs.py
Or: python diagnose_orphaned_orgs.py (if Django is configured)
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from apps.organizations.models import Organization, Membership
from apps.auth.models import User
from django.db.models import Count

def diagnose():
    print("=" * 60)
    print("ORGANIZATION-USER DATA DIAGNOSIS")
    print("=" * 60)
    
    # Count total users and organizations
    total_users = User.objects.count()
    total_orgs = Organization.objects.count()
    total_memberships = Membership.objects.count()
    
    print(f"\n📊 COUNTS:")
    print(f"  Total Users: {total_users}")
    print(f"  Total Organizations: {total_orgs}")
    print(f"  Total Memberships: {total_memberships}")
    
    # Find organizations with no memberships (orphaned)
    orgs_with_member_counts = Organization.objects.annotate(
        member_count=Count('memberships')
    )
    
    orphaned_orgs = orgs_with_member_counts.filter(member_count=0)
    orgs_with_members = orgs_with_member_counts.filter(member_count__gt=0)
    
    print(f"\n🔍 ANALYSIS:")
    print(f"  Organizations with members: {orgs_with_members.count()}")
    print(f"  Orphaned organizations (no members): {orphaned_orgs.count()}")
    
    if orphaned_orgs.exists():
        print(f"\n⚠️  ORPHANED ORGANIZATIONS FOUND:")
        print("-" * 50)
        for org in orphaned_orgs[:20]:  # Show first 20
            print(f"  ID: {org.id}")
            print(f"  Name: {org.name}")
            print(f"  Slug: {org.slug}")
            print(f"  Created: {org.created_at}")
            print(f"  Plan: {org.plan_tier}")
            print("-" * 50)
        
        if orphaned_orgs.count() > 20:
            print(f"  ... and {orphaned_orgs.count() - 20} more")
    
    # Check for discrepancy
    expected_orgs = total_users  # If 1 org per user
    discrepancy = total_orgs - orgs_with_members.count()
    
    print(f"\n📈 SUMMARY:")
    print(f"  Expected: Each user should have 1 organization")
    print(f"  Actual users: {total_users}")
    print(f"  Organizations with at least 1 member: {orgs_with_members.count()}")
    print(f"  Orphaned organizations: {orphaned_orgs.count()}")
    print(f"  Discrepancy: {discrepancy} orphaned orgs")
    
    if discrepancy > 0:
        print(f"\n💡 ROOT CAUSE:")
        print(f"  When a user is deleted, their Membership records are cascade-deleted,")
        print(f"  but the Organization remains orphaned in the database.")
        print(f"\n🛠️  RECOMMENDED FIX:")
        print(f"  1. Run the cleanup script to delete orphaned organizations")
        print(f"  2. Update the user deletion logic to cascade-delete single-owner organizations")
    
    return {
        'total_users': total_users,
        'total_orgs': total_orgs,
        'orphaned_count': orphaned_orgs.count(),
        'orphaned_org_ids': list(orphaned_orgs.values_list('id', flat=True))
    }

if __name__ == '__main__':
    result = diagnose()
    print(f"\n✅ Diagnosis complete.")
