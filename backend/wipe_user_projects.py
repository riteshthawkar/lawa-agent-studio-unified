import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
django.setup()

from django.contrib.auth import get_user_model
from apps.sites.models import Site
from apps.organizations.models import Membership

User = get_user_model()
target_email = "prashantthawkar172003@gmail.com"

print(f"--- Wiping Projects for {target_email} ---")

try:
    user = User.objects.get(email=target_email)
except User.DoesNotExist:
    print("User NOT found!")
    sys.exit(1)

# Get user orgs
memberships = Membership.objects.filter(user=user)
org_ids = memberships.values_list('organization_id', flat=True)

print(f"Found {len(org_ids)} organizations for user.")

# Delete sites in these organizations
sites = Site.objects.filter(org_id__in=org_ids)
count = sites.count()
print(f"Found {count} sites to delete.")

if count > 0:
    # Delete generic "orphaned" sites that might be attributed to this user by domain pattern if we want to be thorough?
    # The user said "remove every project".
    # Let's also check for sites with no org_id but created by this user? (No created_by field).
    # We will stick to org-based deletion + known domain matches if needed.
    # For now, org-based is safest 'fresh start' for the dashboard.
    
    # Also delete any sites that match the domains we saw earlier if they are orphan?
    # https://omkarthawakar.github.io
    
    deleted_count, _ = sites.delete()
    print(f"Deleted {deleted_count} sites and related objects.")

print("--- Wipe Complete ---")
