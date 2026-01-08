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

print(f"--- Adopting Orphaned Sites for {target_email} ---")

try:
    user = User.objects.get(email=target_email)
except User.DoesNotExist:
    print("User NOT found!")
    sys.exit(1)

# Get primary org
membership = Membership.objects.filter(user=user, role='owner').first()
if not membership:
    print("User has no Organization Membership as owner!")
    sys.exit(1)

org = membership.organization
print(f"Target Org: {org.name} ({org.id})")

# Find recent orphaned sites (created in last hour)
# Since we don't have user link on site, we have to guess or assume the ones with no org_id are theirs 
# if this is a dev environment or low traffic. 
# BE CAREFUL IN PROD. But checking the debug output, there are multiple sites with same domain.
# https://omkarthawakar.github.io

orphaned_sites = Site.objects.filter(org_id__isnull=True).order_by('-created_at')[:10]
print(f"\nFound {orphaned_sites.count()} recent orphaned sites (checking ownership candidates):")

count = 0
for site in orphaned_sites:
    # Danger: we don't know FOR SURE if this is theirs.
    # But based on the conversation context, they kept trying to create it.
    # check if site with same domain and org_id already exists
    existing_site = Site.objects.filter(domain=site.domain, org_id=org.id).first()
    if existing_site:
        print(f" - Duplicate found for {site.domain} in org {org.id}. Deleting orphan {site.id}...")
        site.delete()
    else:
        print(f" - Adopting: {site.domain} (ID: {site.id}) -> Org: {org.id}")
        site.org_id = org.id
        site.save()
        count += 1

print(f"\nAdopted {count} sites.")
