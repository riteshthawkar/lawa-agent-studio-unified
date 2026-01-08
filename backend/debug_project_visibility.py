import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
django.setup()

from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.core.organization_permissions import get_user_organizations

User = get_user_model()
target_email = "prashantthawkar172003@gmail.com"

print(f"--- Debugging Project Visibility for {target_email} ---")

try:
    user = User.objects.get(email=target_email)
    print(f"User Found: ID={user.id}, Is Active={user.is_active}")
except User.DoesNotExist:
    print("User NOT found!")
    sys.exit(1)

# Check Memberships
memberships = Membership.objects.filter(user=user)
print(f"\nMemberships ({memberships.count()}):")
for m in memberships:
    print(f" - Org: {m.organization.name} (ID: {m.organization.id}, Status: {m.organization.status}), Role: {m.role}")

# Check Organizations logic (what get_user_organizations returns)
user_orgs = get_user_organizations(user)
print(f"\nAllowed Organizations (via get_user_organizations):")
user_org_ids = []
for org in user_orgs:
    print(f" - {org.name} ({org.id})")
    user_org_ids.append(org.id)

# Check Sites
print(f"\nSites linked to user's User ID ({user.id}) [Direct Ownership Check]:")
# Sites don't have a 'user' field usually, they rely on org_id. Only BaseModel has created_by if configured?
# Let's check Site model fields. It has org_id.
# Check if there are sites with this org_id
sites_in_orgs = Site.objects.filter(org_id__in=user_org_ids)
print(f"\nSites in User's Organizations ({sites_in_orgs.count()}):")
for site in sites_in_orgs:
    print(f" - Site: {site.domain} (ID: {site.id}, OrgID: {site.org_id}, Status: {site.status})")

# Check orphaned sites (if we can find any trace - strictly tricky without user link, 
# but maybe via domain if we knew it, or just checking recent sites)
print("\nRecent 5 Sites Created System-wide:")
for site in Site.objects.order_by('-created_at')[:5]:
    print(f" - {site.domain} | OrgID: {site.org_id} | Created: {site.created_at}")

print("\n--- End Debug ---")
