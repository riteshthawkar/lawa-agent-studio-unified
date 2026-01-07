import pytest
from httpx import AsyncClient
from datetime import datetime

@pytest.mark.asyncio
async def test_start_indexing_no_auth(client: AsyncClient):
    """Test starting indexing without auth header fails"""
    response = await client.post("/index", json={"url": "https://example.com"})
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_start_indexing_invalid_auth(client: AsyncClient):
    """Test starting indexing with invalid token fails"""
    headers = {"Authorization": "Bearer wrong-token"}
    response = await client.post("/index", json={"url": "https://example.com"}, headers=headers)
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_start_indexing_success(client: AsyncClient, mock_db_manager):
    """Test successful task creation"""
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "url": "https://example.com",
        "max_pages": 50
    }
    
    response = await client.post("/index", json=payload, headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "task_id" in data
    assert data["url"].rstrip("/") == "https://example.com"
    
    # Verify DB call
    assert mock_db_manager.create_task.called
    # Check if task was added to background tasks (Implied by response success for now)

@pytest.mark.asyncio
async def test_start_indexing_validation_error(client: AsyncClient):
    """Test invalid URL fails validation"""
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "url": "not-a-url",
        "max_pages": 50
    }
    
    response = await client.post("/index", json=payload, headers=headers)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_start_indexing_idempotency(client: AsyncClient, mock_db_manager):
    """Test idempotency with external_job_id"""
    mock_db_manager.get_task_by_external_job.return_value = {
        "task_id": "existing-task-id",
        "status": "processing",
        "url": "https://example.com",
        "created_at": datetime.now().isoformat()
    }
    
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "url": "https://example.com",
        "external_job_id": "job-123"
    }
    
    response = await client.post("/index", json=payload, headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "existing-task-id"
    assert data["message"] == "Existing task returned (idempotent)"
    assert mock_db_manager.create_task.called is False  # Should not create new task

@pytest.mark.asyncio
async def test_get_tasks_list(client: AsyncClient, mock_db_manager):
    """Test listing tasks"""
    mock_db_manager.list_tasks.return_value = [
        {
            "task_id": "t1",
            "status": "completed",
            "url": "https://example.com",
            "created_at": datetime.now().isoformat(),
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat()
        }
    ]
    
    response = await client.get("/tasks")
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["task_id"] == "t1"

@pytest.mark.asyncio
async def test_get_task_detail(client: AsyncClient, mock_db_manager):
    """Test getting single task detail"""
    mock_db_manager.get_task.return_value = {
        "task_id": "t1",
        "status": "completed",
        "created_at": datetime.now().isoformat(),
        "phase1_result": {},
        "phase2_result": {}
    }
    
    response = await client.get("/tasks/t1")
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "t1"
    assert data["status"] == "completed"

@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient, mock_db_manager):
    """Test 404 for non-existent task"""
    mock_db_manager.get_task.return_value = None
    
    response = await client.get("/tasks/unknown")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_cancel_task(client: AsyncClient, mock_db_manager):
    """Test cancelling an active task"""
    mock_db_manager.get_task.return_value = {"task_id": "t1", "status": "processing"}
    
    response = await client.delete("/tasks/t1")
    assert response.status_code == 200
    assert mock_db_manager.update_task_status.called

@pytest.mark.asyncio
async def test_cancel_task_invalid_state(client: AsyncClient, mock_db_manager):
    """Test cancelling a completed task fails"""
    mock_db_manager.get_task.return_value = {"task_id": "t1", "status": "completed"}
    
    response = await client.delete("/tasks/t1")
    assert response.status_code == 400
