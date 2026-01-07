import os
import django
import sys

# Setup Django environment
sys.path.append(os.path.join(os.getcwd(), 'backend'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lawa_platform.settings")
django.setup()

from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.auth.models import EmailVerification

def wipe_all_data():
    print("WARNING: This will delete ALL users, sites, and data.")
    
    # 1. Delete IndexingJobs
    count, _ = IndexingJob.objects.all().delete()
    print(f"Deleted {count} IndexingJobs.")

    # 2. Delete Sites
    count, _ = Site.objects.all().delete()
    print(f"Deleted {count} Sites.")

    # 3. Delete Memberships (should cascade from User, but safe to do)
    count, _ = Membership.objects.all().delete()
    print(f"Deleted {count} Memberships.")

    # 4. Delete Organizations
    count, _ = Organization.objects.all().delete()
    print(f"Deleted {count} Organizations.")

    # 5. Delete EmailVerifications
    count, _ = EmailVerification.objects.all().delete()
    print(f"Deleted {count} EmailVerifications.")

    # 6. Delete Users
    User = get_user_model()
    # Delete ALL users including demo (will recreate)
    count, _ = User.objects.all().delete()
    print(f"Deleted {count} Users.")

    # 7. Recreate Demo User
    demo_email = "demo@webbotify.com"
    demo_password = "password123"
    print(f"Recreating demo user: {demo_email}")
    user = User.objects.create_user(username=demo_email, email=demo_email, password=demo_password)
    user.is_email_verified = True
    user.save()
    
    print("DONE. Clean slate with only demo user.")

if __name__ == "__main__":
    try:
        wipe_all_data()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
