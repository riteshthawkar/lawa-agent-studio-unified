import requests
import os
import json
import time

API_URL = "http://localhost:8002/index"
API_TOKEN = "TKhPt8qX7ZX8Q6A65E3BowcsNI2yUJZC96BXqmXqj"

payload = {
    "url": "https://example.com",
    "site_id": "https://example.com",
    "max_pages": 1,
    "pinecone_index": "webbotify-index-3072",
    "embed_model": "gemini-embedding-001"
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_TOKEN}"
}

print(f"Triggering indexing job for {payload['url']}...")
try:
    response = requests.post(API_URL, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        task_id = response.json().get("task_id")
        print(f"Task ID: {task_id}")
        
        # Poll for completion
        print("Polling for completion...")
        for _ in range(30):
            time.sleep(2)
            try:
                status_url = f"http://localhost:8002/tasks?external_job_id={payload.get('external_job_id')}"
                # Or verify list endpoint logic usually returns list
                # Inspecting app.py: /tasks returns TaskList
                
                # Better: get task by ID if endpoint exists, or filter list
                # There is no direct /tasks/{id} in app.py I saw, but /tasks has filters.
                # Actually app.py doesn't have /tasks/{id} exposed?
                # It has list_tasks.
                
                list_resp = requests.get(f"http://localhost:8002/tasks?limit=10", headers=headers)
                if list_resp.status_code == 200:
                    tasks = list_resp.json().get("results", [])
                    my_task = next((t for t in tasks if t["task_id"] == task_id), None)
                    if my_task:
                        print(f"Status: {my_task['status']}, Pages Indexed: {my_task.get('progress', {}).get('documents_indexed')} (Docs) / {my_task.get('result', {}).get('stats', {}).get('urls_successful') if my_task.get('result') else 'N/A'} (Success)")
                        # Also check the top-level 'pages_indexed' if my_task has it (app.py TaskStatus model might not have it?)
                        # TaskStatus model has progress dict.
                        
                        if my_task["status"] in ["completed", "failed"]:
                            print("Task Completed!")
                            print(json.dumps(my_task, indent=2))
                            break
            except Exception as e:
                print(f"Polling error: {e}")
                
except Exception as e:
    print(f"Request failed: {e}")

