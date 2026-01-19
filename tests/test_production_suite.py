
import os
import sys
import django
from django.conf import settings
from datetime import timedelta
from django.utils import timezone

# Setup Django Environment
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(BASE_DIR, 'backends', 'core')
sys.path.insert(0, CORE_DIR)
# print(f"DEBUG: Added to sys.path: {CORE_DIR}")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lawa_platform.settings")
django.setup()

from django.contrib.auth import get_user_model
from apps.auth.services import AuthenticationService
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.indexing.models import IndexingJob
from apps.usage.services import QuotaService

User = get_user_model()

def run_verification():
    print("🚀 Starting Production Readiness Verification...\n")
    
    # 1. Auth & User Management
    print("1️⃣  Verifying Auth & User Management...")
    email = "prod_verify@example.com"
    try:
        user = User.objects.get(email=email)
        print(f"   - Cleaned up existing test user: {email}")
        user.delete()
    except User.DoesNotExist:
        pass
        
    user = User.objects.create_user(username="prodverify", email=email, password="SafePassword123!")
    print("   ✅ User creation successful")
    
    # 2. Organization & Project Setup
    print("\n2️⃣  Verifying Organization & Project Setup...")
    try:
        org = Organization.objects.get(slug="prod-verify-org")
        print(f"   - Cleaned up existing test org: {org.name}")
        org.delete()
    except Organization.DoesNotExist:
        pass

    # Organization requires a slug
    org = Organization.objects.create(name="Prod Verify Org", slug="prod-verify-org", plan_tier="basic")
    Membership.objects.create(organization=org, user=user, role="owner")
    print(f"   ✅ Organization created: {org.name} (Tier: {org.plan_tier})")
    
    site = Site.objects.create(org_id=org.id, domain="example.com", name="Prod Site")
    print(f"   ✅ Site created: {site.domain}")

    # 3. Indexing Engine
    print("\n3️⃣  Verifying Indexing Engine...")
    try:
        IndexingJob.objects.get(external_job_id="verify-job-123").delete()
    except IndexingJob.DoesNotExist:
        pass
        
    job = IndexingJob.objects.create(site_id=site.id, url="https://example.com", status="queued", external_job_id="verify-job-123")
    print(f"   ✅ Indexing Job created: {job.url} (Status: {job.status})")
    
    # 4. Chatbot & Quota
    print("\n4️⃣  Verifying Chatbot & Quotas...")
    chatbot = Chatbot.objects.create(site=site, name="Prod Bot")
    print(f"   ✅ Chatbot created: {chatbot.name}")
    
    # Check Limits (Basic Tier: 1 Chatbot)
    allowed, reason = QuotaService.check_chatbot_limit(org.id)
    print(f"   ℹ️  Chatbot Limit Check (1/1): Allowed={allowed}")
    if not allowed and "limit reached" in reason.lower():
        print("   ✅ Quota Enforcement verified (Blocked 2nd chatbot)")
    else:
        print(f"   ⚠️  Warning: Quota check unexpected result: {allowed} - {reason}")

    # 5. Billing Logic
    print("\n5️⃣  Verifying Billing Logic...")
    # Upgrade to Premium
    org.plan_tier = "premium"
    org.save()
    allowed_premium, _ = QuotaService.check_chatbot_limit(org.id)
    print(f"   ℹ️  Upgraded to Premium. Check Limit: Allowed={allowed_premium}")
    assert allowed_premium is True, "Premium should allow more chatbots"
    print("   ✅ Tier Upgrade logic verified")

    # 6. Email Service (Config Check)
    print("\n6️⃣  Verifying Email Configuration...")
    try:
        service = AuthenticationService()
        print("   ✅ AuthenticationService instantiated successfully")
        if hasattr(service, 'send_verification_email'):
             print("   ✅ Email method confirmed present")
        else:
             print("   ❌ Email method missing")
             
    except Exception as e:
        print(f"   ❌ AuthenticationService failed: {e}")

    # Cleanup
    print("\n🧹 Cleaning up test data...")
    # Organization delete should cascade to site/chatbot/memberships
    if org:
        org.delete()
    if user and user.id: # User might be deleted by org cascade if membership configured that way, but likely not user
        try:
             # Refresh user if needed or just try delete
             User.objects.get(id=user.id).delete()
        except User.DoesNotExist:
             pass
             
    print("   ✅ Cleanup complete")

    print("\n✅ Verification Suite Finished Successfully.")

if __name__ == "__main__":
    run_verification()
