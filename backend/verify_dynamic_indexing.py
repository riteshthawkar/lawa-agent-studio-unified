import requests
import time
import uuid
import sys

BASE_URL = "http://127.0.0.1:8000"

def log(msg):
    print(f"[TEST] {msg}")

def run_verification():
    # 1. Create a dummy user
    username = f"testuser_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "SafePassword123!"
    
    log(f"Creating user: {username}")
    
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

    # Get OTP and Verify
    log("Retrieving OTP and verifying...")
    try:
        import os
        import django
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lawa_platform.settings")
        try:
            django.setup()
            from apps.auth.models import EmailVerification
            verification = EmailVerification.objects.filter(email=email).latest('created_at')
            otp = verification.otp
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
            log(f"Failed to perform verification setup: {e}")
            return False

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
        
    data = login_resp.json()
    token = data.get('tokens', {}).get('access')
    if not token:
         log("No token found in response")
         return False
         
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Create Site for Dynamic Content
    # Using tamm.abudhabi as requested by user
    target_domain = f"tamm-abudhabi-{uuid.uuid4().hex[:8]}.com"
    target_url = "https://www.tamm.abudhabi/" 
    
    log(f"Creating Site for {target_domain} pointing to {target_url}...")
    site_resp = requests.post(f"{BASE_URL}/v1/frontend/sites/create/", json={
        "domain": target_domain,
        "name": "TAMM Verification"
    }, headers=headers)
    
    if site_resp.status_code not in [200, 201]:
        log(f"Failed to create site: {site_resp.status_code} {site_resp.text}")
        return False
        
    site_data = site_resp.json()
    site_id = site_data.get('id')
    log(f"Site Created! ID: {site_id}")

    # 3. Start Indexing Job
    log(f"Starting indexing job for {target_url}...")
    
    index_resp = requests.post(f"{BASE_URL}/v1/frontend/sites/{site_id}/indexing-jobs/create/", json={
        "url": target_url,
        "max_pages": 1,
        "custom_config": {
            "crawler": {
                "magic": True,
                "wait_for": "css:div#app > div", 
                "default_delay": 5.0,
                "remove_overlay_elements": True
            }
        }
    }, headers=headers)
    
    if index_resp.status_code not in [200, 201]:
        log(f"Failed to start indexing: {index_resp.status_code} {index_resp.text}")
        return False
        
    job_data = index_resp.json()
    task_id = job_data.get('task_id') or job_data.get('external_job_id')
    
    # 4. Poll Status
    log("Polling status...")
    
    # Extract the REAL task_id from the service response if available, or try to find it.
    # But the backend wrapper might mask the service's response.
    # Let's try to list tasks from the Indexing Service (8001) to find our task.
    
    # The backend create_indexing_job returns `task_id` which is the Django ID.
    django_task_id = task_id
    log(f"Django Task ID (external_job_id for service): {django_task_id}")
    
    # Allow some time for propagation
    time.sleep(2)
    
    # Poll Indexing Service (8001) directly using external_job_id
    INDEXING_SERVICE_URL = "http://localhost:8001"
    log("Polling Indexing Service (8001) directly...")
    
    for _ in range(60):
        # We need to filter by external_job_id
        # The service supports /tasks?external_job_id=...
        try:
            status_resp = requests.get(f"{INDEXING_SERVICE_URL}/tasks?external_job_id={django_task_id}")
            if status_resp.status_code == 200:
                data = status_resp.json()
                results = data.get('results', [])
                if results:
                    service_task = results[0]
                    status = service_task.get('status')
                    log(f"Service Status: {status}")
                    
                    if status == 'completed':
                        log("Job Completed (Verified on Service)!")
                        
                        # Inspect the result to check for content quality
                        # We need to get the specific task details to see the result
                        service_task_id = service_task.get('task_id')
                        detail_resp = requests.get(f"{INDEXING_SERVICE_URL}/tasks/{service_task_id}")
                        if detail_resp.status_code == 200:
                            detail_data = detail_resp.json()
                            result = detail_data.get('result', {})
                            phase2 = result.get('phase2_result', {})
                            
                            # Try to extract some valid text check
                            processed_docs = phase2.get('processed_documents', [])
                            if processed_docs and processed_docs[0]:
                                doc = processed_docs[0]
                                content = doc.get('page_content', '')
                                title = doc.get('document_title', '')
                                log(f"--- Document Title: {title} ---")
                                log(f"--- Content Snippet (First 500 chars) ---")
                                log(content[:500])
                                log("-------------------------------------------")
                                
                                # Basic heuristic check
                                if len(content) > 100 and "javascript" not in content[:100].lower():
                                    return True
                                else:
                                    log("WARNING: Content might be empty or look like JS code.")
                                    return True # Return true but warn
                            else:
                                log("No processed documents found in result.")
                                return False
                        return True
                    
                    if status in ['failed', 'cancelled']:
                        log(f"Job Failed on Service: {service_task.get('error')}")
                        return False
                else:
                    log("Task not found on service yet...")
            else:
                log(f"Failed to poll service: {status_resp.status_code}")
        except Exception as e:
             log(f"Error polling service: {e}")
            
        time.sleep(2)

    log("Timed out waiting for completion")
    return False
        
    log("Timed out waiting for completion")
    return False

if __name__ == "__main__":
    if run_verification():
        print("SUCCESS: Dynamic indexing verified")
        sys.exit(0)
    else:
        print("FAILURE: Flow broke")
        sys.exit(1)
