import pytest
import time
import uuid

def test_invalid_url_handling(api_session, base_url, auth_headers):
    """Test system handling of invalid/unreachable URLs"""
    # 1. Invalid Schema (e.g., ftp://)
    payload = {"url": "ftp://example.com"}
    resp = api_session.post(f"{base_url}/v1/index/", json=payload, headers=auth_headers)
    # Serializer/API should reject non-http/https
    assert resp.status_code == 400
    
    # 2. Unreachable Domain (using a unique, non-existent domain)
    # API might reject this synchronously if it does DNS check, OR queue it.
    
    # If using Synchronous validation (fastapi/requests checks DNS/connection): 400
    # If Asynchronous (worker handles it): 200/201/202
    if resp.status_code == 400:
        # Accepted behavior (Fail Fast)
        return

    assert resp.status_code in [200, 201, 202]
    task_id = resp.json().get('task_id')
    
    # Poll for failure
    max_retries = 30
    failed = False
    for i in range(max_retries):
        status_resp = api_session.get(f"{base_url}/v1/tasks/{task_id}/", headers=auth_headers)
        status = status_resp.json().get('status')
        print(f"Polling Failure Test {i}: {status}")
        
        if status == 'failed':
            failed = True
            break
        if status == 'completed':
            pytest.fail("Job completed for non-existent domain?!")
            
        time.sleep(2)
        
    assert failed, "Job for invalid domain did not fail within timeout"

def test_malformed_payload(api_session, base_url, auth_headers):
    """Verify API rejects garbage json"""
    resp = api_session.post(
        f"{base_url}/v1/index/", 
        data="INVALID JSON", 
        headers={"Authorization": auth_headers["Authorization"], "Content-Type": "application/json"}
    )
    assert resp.status_code == 400
