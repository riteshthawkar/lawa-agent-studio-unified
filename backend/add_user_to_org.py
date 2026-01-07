import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
django.setup()
from django.contrib.auth import get_user_model
from apps.sites.models import Site
from apps.organizations.models import Membership, Organization

User = get_user_model()
user = User.objects.get(email='testuser@example.com')
site = Site.objects.first()

if site and site.org_id:
    # Ensure Organization exists (Site might store UUID only if it's a legacy field or foreign key)
    # Check if foreign key
    if hasattr(site, 'organization'):
         org = site.organization
    else:
         # Try to get or create organization with that ID
         org_id = site.org_id
         org, created = Organization.objects.get_or_create(id=org_id, defaults={'name': 'Test Org'})
    
    # Add membership
    Membership.objects.get_or_create(user=user, organization=org, defaults={'role': 'admin'})
    print(f"Added user {user.email} to organization {org.id}")
else:
    print("No site or org_id found.")
