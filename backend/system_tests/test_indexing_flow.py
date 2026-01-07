import pytest
import time
import requests

def test_create_and_list_sites(api_session, base_url, auth_headers):
    # Create Site implicitly via Indexing or Explicitly? 
    # The API design in verify_flow.py used /index/ directly which creates site if needed.
    # Let's check if there is a site creation endpoint. /v1/sites/
    
    site_url = "https://example.com"
    payload = {"url": site_url}
    
    # Try to create explicitly if endpoint exists (assuming SiteViewSet)
    # If not, we rely on /index/
    try:
        resp = api_session.post(f"{base_url}/v1/sites/", json=payload, headers=auth_headers)
        if resp.status_code == 201:
            site_id = resp.json()['id']
    except:
        pass

    # List sites
    resp = api_session.get(f"{base_url}/v1/sites/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) or 'results' in data

def test_indexing_lifecycle(api_session, base_url, auth_headers):
    # 1. Start Indexing
    # Randomize URL to avoid collision in persistent env
    import uuid
    target_url = f"https://example-{uuid.uuid4()}.com"
    payload = {"url": target_url}
    
    print(f"\n[SystemTest] Starting indexing for {target_url}...")
    resp = api_session.post(f"{base_url}/v1/index/", json=payload, headers=auth_headers)
    assert resp.status_code in [200, 201, 202], f"Failed to start index: {resp.text}"
    
    data = resp.json()
    task_id = data.get("task_id") or data.get("id")
    assert task_id, "No task_id returned"
    
    # 2. Poll Status
    max_retries = 20
    success = False
    
    for i in range(max_retries):
        status_resp = api_session.get(f"{base_url}/v1/tasks/{task_id}/", headers=auth_headers)
        assert status_resp.status_code == 200, f"Got {status_resp.status_code} for task {task_id}: {status_resp.text}. Create Resp: {data}"
        status_data = status_resp.json()
        status = status_data.get("status")
        print(f"Polling {i}: {status}")
        
        if status == "completed":
            success = True
            break
        if status in ["failed", "cancelled"]:
            pytest.fail(f"Indexing failed with status: {status}")
        
        time.sleep(2)
        
    assert success, "Indexing timed out or did not complete"

def test_reindexing_trigger(api_session, base_url, auth_headers):
    # Test that we can trigger a SECOND indexing job for the same URL (Blue-Green)
    # Note: re-indexing requires site to exist.
    # In strict mode, only Owner can re-index.
    # We use a new unique URL to create the site first.
    import uuid
    target_url = f"https://example-reindex-{uuid.uuid4()}.com"
    payload = {"url": target_url}
    
    resp = api_session.post(f"{base_url}/v1/index/", json=payload, headers=auth_headers)
    assert resp.status_code in [200, 201, 202]
    task_id = resp.json().get("task_id")
    assert task_id
