import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
import sys
import os
from pathlib import Path
from httpx import AsyncClient, ASGITransport

# Add project root to path so we can import app
sys.path.append(str(Path(__file__).parent.parent))

# Mock the django_setup module BEFORE importing app
# This prevents Django from trying to initialize during test collection
sys.modules["django_setup"] = MagicMock()
sys.modules["django_setup"].setup_django = MagicMock()

# Mock the database manager
db_manager_mock = AsyncMock()
db_manager_mock.create_task = AsyncMock()
db_manager_mock.update_task_status = AsyncMock()
db_manager_mock.get_task = AsyncMock(return_value=None)
db_manager_mock.list_tasks = AsyncMock(return_value=[])
db_manager_mock.claim_and_start_task = AsyncMock(return_value=True)

# Patch the module where db_manager is imported
import modules.django_database
modules.django_database.db_manager = db_manager_mock

from app import app

@pytest.fixture
def mock_db_manager():
    return db_manager_mock

@pytest.fixture
def override_env_vars(monkeypatch):
    """Set necessary env vars for testing"""
    monkeypatch.setenv("INDEXING_API_TOKEN", "test-token")
    monkeypatch.setenv("PINECONE_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("WEBHOOK_SIGNING_SECRET", "fake-secret")

@pytest_asyncio.fixture
async def client(override_env_vars):
    """Async Client fixture for FastAPI"""
    # Use ASGITransport for direct app testing
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset mocks before each test"""
    db_manager_mock.reset_mock()
    db_manager_mock.get_task_by_external_job.return_value = None
    db_manager_mock.create_task.return_value = None

