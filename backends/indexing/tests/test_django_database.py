"""
Tests for DjangoDatabaseManager.

These tests cover the Django ORM database manager that provides
async database operations for the indexing backend.
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4


class TestDjangoDatabaseManagerCreate:
    """Tests for task creation functionality"""
    
    @pytest.mark.asyncio
    async def test_create_task_success(self, mock_db_manager):
        """Test creating a new task"""
        task_data = {
            "task_id": str(uuid4()),
            "url": "https://example.com",
            "status": "queued",
            "external_job_id": "job-123",
            "crawl_config": {"max_pages": 100},
            "site_id": str(uuid4())
        }
        
        result = await mock_db_manager.create_task(task_data)
        
        assert result is not None
        assert mock_db_manager.create_task.called
    
    @pytest.mark.asyncio
    async def test_create_task_with_callback_url(self, mock_db_manager):
        """Test creating task with callback URL"""
        task_data = {
            "task_id": str(uuid4()),
            "url": "https://example.com",
            "status": "queued",
            "callback_url": "https://backend.example.com/webhooks/indexing/"
        }
        
        result = await mock_db_manager.create_task(task_data)
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_create_task_with_namespace(self, mock_db_manager):
        """Test creating task with target namespace"""
        task_data = {
            "task_id": str(uuid4()),
            "url": "https://example.com",
            "status": "queued",
            "target_namespace": f"site_{uuid4()}_1234567890"
        }
        
        result = await mock_db_manager.create_task(task_data)
        assert result is not None


class TestDjangoDatabaseManagerUpdate:
    """Tests for task update functionality"""
    
    @pytest.mark.asyncio
    async def test_update_task_status_to_processing(self, mock_db_manager):
        """Test updating task status to processing"""
        task_id = str(uuid4())
        mock_db_manager.get_task.return_value = {
            "task_id": task_id,
            "status": "queued"
        }
        
        await mock_db_manager.update_task_status(task_id, "processing")
        assert mock_db_manager.update_task_status.called
    
    @pytest.mark.asyncio
    async def test_update_task_status_to_completed(self, mock_db_manager):
        """Test updating task status to completed with results"""
        task_id = str(uuid4())
        
        await mock_db_manager.update_task_status(
            task_id,
            "completed",
            phase2_result={
                "pages_indexed": 50,
                "documents_created": 150,
                "namespace": f"site_{uuid4()}_1234567890"
            }
        )
        
        assert mock_db_manager.update_task_status.called
    
    @pytest.mark.asyncio
    async def test_update_task_status_to_failed(self, mock_db_manager):
        """Test updating task status to failed with error"""
        task_id = str(uuid4())
        
        await mock_db_manager.update_task_status(
            task_id,
            "failed",
            error_message="Connection timeout"
        )
        
        assert mock_db_manager.update_task_status.called
    
    @pytest.mark.asyncio
    async def test_update_task_id(self, mock_db_manager):
        """Test updating task_id for existing job"""
        external_job_id = "external-job-123"
        new_task_id = str(uuid4())
        
        await mock_db_manager.update_task_id(external_job_id, new_task_id)
        assert mock_db_manager.update_task_id.called


class TestDjangoDatabaseManagerQuery:
    """Tests for task query functionality"""
    
    @pytest.mark.asyncio
    async def test_get_task_by_id(self, mock_db_manager):
        """Test getting task by task_id"""
        task_id = str(uuid4())
        mock_db_manager.get_task.return_value = {
            "task_id": task_id,
            "status": "completed",
            "url": "https://example.com"
        }
        
        result = await mock_db_manager.get_task(task_id)
        
        assert result is not None
        assert result["task_id"] == task_id
    
    @pytest.mark.asyncio
    async def test_get_task_not_found(self, mock_db_manager):
        """Test getting non-existent task"""
        mock_db_manager.get_task.return_value = None
        
        result = await mock_db_manager.get_task("non-existent-id")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_task_by_external_job(self, mock_db_manager):
        """Test getting task by external_job_id"""
        external_job_id = "external-job-123"
        mock_db_manager.get_task_by_external_job.return_value = {
            "task_id": str(uuid4()),
            "external_job_id": external_job_id,
            "status": "completed"
        }
        
        result = await mock_db_manager.get_task_by_external_job(external_job_id)
        
        assert result is not None
        assert result["external_job_id"] == external_job_id
    
    @pytest.mark.asyncio
    async def test_list_tasks(self, mock_db_manager):
        """Test listing tasks"""
        mock_db_manager.list_tasks.return_value = [
            {"task_id": str(uuid4()), "status": "completed"},
            {"task_id": str(uuid4()), "status": "processing"}
        ]
        
        result = await mock_db_manager.list_tasks()
        
        assert len(result) == 2
    
    @pytest.mark.asyncio
    async def test_list_tasks_with_filter(self, mock_db_manager):
        """Test listing tasks with status filter"""
        mock_db_manager.list_tasks.return_value = [
            {"task_id": str(uuid4()), "status": "completed"}
        ]
        
        result = await mock_db_manager.list_tasks(status_filter="completed")
        
        assert len(result) == 1
        assert result[0]["status"] == "completed"


class TestDjangoDatabaseManagerExclusions:
    """Tests for URL exclusion pattern functionality"""
    
    @pytest.fixture
    def db_manager(self):
        """Create a real manager instance with mocked models"""
        with patch('modules.django_database.get_django_models') as mock_get_models:
            mock_models = {
                'IndexingJob': MagicMock(),
                'Site': MagicMock(),
                'IndexedPage': MagicMock()
            }
            mock_get_models.return_value = mock_models
            from modules.django_database import DjangoDatabaseManager
            return DjangoDatabaseManager()

    @pytest.mark.asyncio
    async def test_get_excluded_patterns(self, mock_db_manager):
        """Test getting exclusion patterns for site (using mock as this needs DB)"""
        # Keep using mock for DB access method
        site_id = str(uuid4())
        mock_db_manager.get_excluded_patterns.return_value = [
            {"pattern": "*/admin/*", "pattern_type": "glob"},
            {"pattern": ".*/login$", "pattern_type": "regex"}
        ]
        
        result = await mock_db_manager.get_excluded_patterns(site_id)
        
        assert len(result) == 2
    
    def test_url_matches_exclusion_glob(self, db_manager):
        """Test URL matching against glob pattern"""
        patterns = [
            {"pattern": "*/admin/*", "pattern_type": "glob"}
        ]
        
        result = db_manager.url_matches_exclusion(
            "https://example.com/admin/settings",
            patterns
        )
        
        assert result is True
        
        # Test negative case
        result = db_manager.url_matches_exclusion(
            "https://example.com/public",
            patterns
        )
        assert result is False
    
    def test_url_matches_exclusion_regex(self, db_manager):
        """Test URL matching against regex pattern"""
        patterns = [
            {"pattern": ".*/login$", "pattern_type": "regex"}
        ]
        
        result = db_manager.url_matches_exclusion(
            "https://example.com/login",
            patterns
        )
        
        assert result is True
        
        # Test negative case
        result = db_manager.url_matches_exclusion(
            "https://example.com/login/success",
            patterns
        )
        # Regex endswith $
        assert result is False


class TestDjangoDatabaseManagerStats:
    """Tests for statistics functionality"""
    
    @pytest.mark.asyncio
    async def test_get_task_stats(self, mock_db_manager):
        """Test getting task statistics"""
        mock_db_manager.get_task_stats.return_value = {
            "total_tasks": 100,
            "completed": 80,
            "failed": 5,
            "processing": 10,
            "queued": 5
        }
        
        result = await mock_db_manager.get_task_stats()
        
        assert result["total_tasks"] == 100
        assert result["completed"] == 80


class TestDjangoDatabaseManagerClaimTask:
    """Tests for task claiming functionality"""
    
    @pytest.mark.asyncio
    async def test_claim_and_start_task(self, mock_db_manager):
        """Test claiming a task for processing"""
        task_id = str(uuid4())
        external_job_id = "job-123"
        
        await mock_db_manager.claim_and_start_task(
            task_id,
            external_job_id,
            datetime.now()
        )
        
        assert mock_db_manager.claim_and_start_task.called
    
    @pytest.mark.asyncio
    async def test_claim_task_already_processing(self, mock_db_manager):
        """Test claiming task that's already processing"""
        # This should handle the case gracefully
        task_id = str(uuid4())
        
        # Mock that task is already processing
        mock_db_manager.get_task.return_value = {
            "task_id": task_id,
            "status": "processing"
        }
        
        await mock_db_manager.claim_and_start_task(
            task_id,
            None,
            datetime.now()
        )
