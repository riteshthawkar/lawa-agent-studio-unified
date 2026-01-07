import requests
import time
import uuid
import sys

BASE_URL = "http://127.0.0.1:8000"
INDEXING_URL = "http://127.0.0.1:8000" # Proxying through Django

def log(msg):
    print(f"[TEST] {msg}")

def run_verification():
    # 1. Create a dummy user
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "SafePassword123!"
    
    log(f"Creating user: {username}")
    
    # We need a registration endpoint. Assuming common Djoser/DRF registration or custom auth
    # Checking lawa_auth or similar. If not available, we might need to assume a superuser or use shell.
    # Let's try to verify via Public API endpoints first, or use a setup script.
    
    # Actually, simpler: Use `manage.py shell` to create user and get token if API is complex
    # But user asked to "use the api endpoints". 
    # Let's try generic signup endpoint often found in /auth/users/ or similar.
    # Checking `backend/lawa_platform/urls.py` in mind (viewed earlier? no).
    
    # Register
    auth_resp = requests.post(f"{BASE_URL}/v1/auth/signup/", json={
        "email": email,
        "username": username,
        "password": password,
        "password_confirm": password,
        "name": "Test User"
    })
    
    if auth_resp.status_code != 201:
        log(f"Failed to register user: {auth_resp.status_code} {auth_resp.text}")
        return False

    # Get OTP and Verify (New Step)
    log("Retrieving OTP and verifying...")
    try:
        # We need to access DB to get the code. Requires django setup if not already done.
        # But wait, this script imports requests, implying it runs as a client script.
        # To mix client requests with DB access, we need to setup Django here.
        import os
        import django
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lawa_platform.settings")
        try:
            django.setup()
        except RuntimeError:
            pass # Already setup

        from apps.auth.models import EmailVerification
        verification = EmailVerification.objects.filter(email=email).latest('created_at')
        otp = verification.otp # Field is 'otp' based on previous context
        log(f"Found OTP: {otp}")

        verify_resp = requests.post(f"{BASE_URL}/v1/auth/verify-email/", json={
            "email": email,
            "otp": otp
        })
        if verify_resp.status_code != 200:
            log(f"Failed to verify email: {verify_resp.status_code} {verify_resp.text}")
            return False
        log("Email verified successfully!")

    except Exception as e:
        log(f"Failed to perform verification: {e}")
        return False

        
    # Login to get Token
    log("Logging in...")
    login_resp = requests.post(f"{BASE_URL}/v1/auth/login/", json={
        "email": email,
        "password": password
    })
    
    if login_resp.status_code != 200:
        log(f"Failed to login: {login_resp.status_code} {login_resp.text}")
        return False
        
    log(f"Login Response: {login_resp.json()}")
    data = login_resp.json()
    tokens = data.get('tokens', {})
    access_token = tokens.get('access')
    if not access_token:
         log("No token found in response")
         return False
         
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 3. Create Site (New Step, required for indexing)
    unique_suffix = uuid.uuid4().hex[:8]
    target_domain = f"example-{unique_suffix}.com"
    target_url = f"https://{target_domain}"
    
    log(f"Creating Site for {target_domain}...")
    site_resp = requests.post(f"{BASE_URL}/v1/frontend/sites/create/", json={
        "domain": target_domain,
        "name": "Test Site"
    }, headers=headers)
    
    if site_resp.status_code not in [200, 201]:
        log(f"Failed to create site: {site_resp.status_code} {site_resp.text}")
        return False
        
    site_data = site_resp.json()
    site_id = site_data.get('id')
    log(f"Site Created! ID: {site_id}")

    # 4. Start Indexing Job (Updated Endpoint)
    log(f"Starting indexing job for {target_url}...")
    
    index_resp = requests.post(f"{BASE_URL}/v1/frontend/sites/{site_id}/indexing-jobs/create/", json={
        "url": target_url,
        "max_pages": 1
    }, headers=headers)
    
    if index_resp.status_code not in [200, 201]:
        log(f"Failed to start indexing: {index_resp.status_code} {index_resp.text}")
        # MVP Note: If 500/Internal Server Error, it might be the Indexing Service failing, check logs.
        # But we verified 8001 is reachable directly.
        return False
        
    job_data = index_resp.json()
    task_id = job_data.get('task_id') or job_data.get('external_job_id')
    
    log(f"Job started! Task ID: {task_id}")
    
    # 5. Poll Status
    log("Polling status...")
    
    for _ in range(60): # Wait up to 120s (Playwright init can be slow)
        status_resp = requests.get(f"{BASE_URL}/v1/tasks/{task_id}/", headers=headers)
        if status_resp.status_code == 200:
            status_data = status_resp.json()
            status = status_data.get('status')
            log(f"Current Status: {status}")
            
            if status == 'completed':
                log("Job Completed!")
                # Optional: Verify results
                return True
                
            if status in ['failed', 'cancelled']:
                log(f"Job Failed: {status_data.get('error')}")
                return False
        
        time.sleep(2)
        
    log("Timed out waiting for completion")
    return False # Timeout is failure in verification


if __name__ == "__main__":
    try:
        if run_verification():
            print("SUCCESS: End-to-End flow verified")
            sys.exit(0)
        else:
            print("FAILURE: Flow broke")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
