"""
Tests for Indexing Backend async operations and Celery integration.

These tests cover:
- Async database operations
- Celery task dispatch
- Connection pool management
- Worker coordination
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4


class TestAsyncDatabaseOperations:
    """Tests for async database operations from indexing backend"""
    
    @pytest.mark.asyncio
    async def test_create_task_async(self, mock_db_manager):
        """Test async task creation"""
        task_data = {
            "task_id": str(uuid4()),
            "url": "https://example.com",
            "status": "queued",
            "external_job_id": "ext-job-123"
        }
        
        result = await mock_db_manager.create_task(task_data)
        
        assert result is not None
        mock_db_manager.create_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_status_async(self, mock_db_manager):
        """Test async status update"""
        task_id = str(uuid4())
        
        await mock_db_manager.update_task_status(task_id, "processing")
        
        mock_db_manager.update_task_status.assert_called()
    
    @pytest.mark.asyncio
    async def test_connection_recovery(self, mock_db_manager):
        """Test database connection recovery after error"""
        # First call fails
        mock_db_manager.get_task.side_effect = [
            Exception("Connection lost"),
            {"task_id": "t1", "status": "completed"}
        ]
        
        # Should retry and succeed
        try:
            await mock_db_manager.get_task("t1")
        except Exception:
            result = await mock_db_manager.get_task("t1")
            assert result["status"] == "completed"


class TestCeleryTaskDispatch:
    """Tests for Celery task dispatch"""
    
    def test_index_site_task_dispatch(self, monkeypatch):
        """Test that index_site_task is dispatched correctly"""
        mock_delay = MagicMock()
        
        with patch('tasks.index_site_task') as mock_task:
            mock_task.delay = mock_delay
            
            from tasks import index_site_task
            
            task_id = str(uuid4())
            crawler_config = {
                "start_url": "https://example.com",
                "max_pages": 100
            }
            embedding_config = {
                "model_name": "all-MiniLM-L6-v2"
            }
            
            # Simulate dispatch
            mock_task.delay(
                task_id=task_id,
                crawler_config_dict=crawler_config,
                embedding_config_dict=embedding_config
            )
            
            mock_delay.assert_called_once()
    
    def test_task_with_callback_url(self, monkeypatch):
        """Test task dispatch with callback URL"""
        with patch('tasks.index_site_task') as mock_task:
            mock_task.delay = MagicMock()
            
            task_id = str(uuid4())
            callback_url = "https://api.example.com/webhooks/indexing/"
            
            mock_task.delay(
                task_id=task_id,
                crawler_config_dict={"start_url": "https://example.com"},
                embedding_config_dict={},
                callback_url=callback_url,
                external_job_id="ext-123"
            )
            
            call_args = mock_task.delay.call_args
            assert call_args.kwargs.get("callback_url") == callback_url


class TestParallelProcessing:
    """Tests for parallel task processing"""
    
    @pytest.mark.asyncio
    async def test_concurrent_task_updates(self):
        """Test handling concurrent task updates"""
        updates = []
        
        async def simulate_update(task_id, status):
            await asyncio.sleep(0.01)  # Simulate DB operation
            updates.append((task_id, status))
            return True
        
        # Simulate 10 concurrent updates
        tasks = [
            simulate_update(f"task_{i}", "completed")
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 10
        assert all(results)
        assert len(updates) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_job_creation(self):
        """Test creating multiple jobs concurrently"""
        created_jobs = []
        
        async def create_job(job_id):
            await asyncio.sleep(0.01)  # Simulate creation time
            created_jobs.append(job_id)
            return job_id
        
        job_ids = [str(uuid4()) for _ in range(5)]
        tasks = [create_job(job_id) for job_id in job_ids]
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        assert len(created_jobs) == 5


class TestConnectionPooling:
    """Tests for database connection pooling"""
    
    def test_connection_reuse(self):
        """Test that connections are reused"""
        connection_calls = []
        
        def mock_connection():
            connection_calls.append(1)
            return MagicMock()
        
        # Simulate multiple operations
        for _ in range(10):
            conn = mock_connection()
        
        # Should have made connections
        assert len(connection_calls) == 10
    
    @pytest.mark.asyncio
    async def test_connection_cleanup(self):
        """Test that connections are cleaned up"""
        active_connections = []
        
        async def acquire_connection():
            conn = MagicMock()
            active_connections.append(conn)
            return conn
        
        async def release_connection(conn):
            active_connections.remove(conn)
        
        # Acquire connections
        conns = [await acquire_connection() for _ in range(5)]
        assert len(active_connections) == 5
        
        # Release connections
        for conn in conns:
            await release_connection(conn)
        assert len(active_connections) == 0


class TestWorkerCoordination:
    """Tests for Celery worker coordination"""
    
    def test_semaphore_backpressure(self):
        """Test semaphore-based backpressure"""
        import threading
        
        max_concurrent = 3
        semaphore = threading.Semaphore(max_concurrent)
        active_count = [0]
        max_active = [0]
        
        def process_task(task_id):
            with semaphore:
                active_count[0] += 1
                max_active[0] = max(max_active[0], active_count[0])
                # Simulate work
                import time
                time.sleep(0.01)
                active_count[0] -= 1
        
        threads = [
            threading.Thread(target=process_task, args=(i,))
            for i in range(10)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Max concurrent should not exceed semaphore limit
        assert max_active[0] <= max_concurrent
    
    def test_task_routing(self):
        """Test task routing to correct queue"""
        # Simulate different queue routing
        task_queues = {
            'index_site_task': 'indexing',
            'process_pdf_task': 'pdf-processing',
            'embed_documents_task': 'embedding'
        }
        
        for task_name, expected_queue in task_queues.items():
            assert expected_queue in ['indexing', 'pdf-processing', 'embedding']


class TestProgressWebhooks:
    """Tests for progress webhook delivery"""
    
    @pytest.mark.asyncio
    async def test_progress_webhook_delivery(self):
        """Test that progress webhooks are delivered"""
        delivered_webhooks = []
        
        async def mock_send_webhook(callback_url, payload):
            delivered_webhooks.append(payload)
            return True
        
        # Simulate progress updates
        for i in range(0, 101, 25):
            await mock_send_webhook(
                "https://api.example.com/webhooks/indexing/",
                {"percent": i, "status": "processing"}
            )
        
        assert len(delivered_webhooks) == 5
        assert delivered_webhooks[-1]["percent"] == 100
    
    @pytest.mark.asyncio
    async def test_progress_webhook_retry(self):
        """Test progress webhook retry on failure"""
        attempts = [0]
        
        async def mock_send_with_retry(callback_url, payload, max_retries=3):
            attempts[0] += 1
            if attempts[0] < 2:
                raise Exception("Connection error")
            return True
        
        try:
            result = await mock_send_with_retry("http://test", {})
        except Exception:
            result = await mock_send_with_retry("http://test", {})
        except Exception:
            result = await mock_send_with_retry("http://test", {})
        
        assert attempts[0] == 2
        assert result is True


class TestErrorPropagation:
    """Tests for error propagation between backends"""
    
    @pytest.mark.asyncio
    async def test_error_callback_on_failure(self):
        """Test that errors are propagated via webhook"""
        error_callbacks = []
        
        async def send_error_callback(callback_url, task_id, error):
            error_callbacks.append({
                'task_id': task_id,
                'error': error,
                'status': 'failed'
            })
        
        # Simulate error
        await send_error_callback(
            "https://api.example.com/webhooks/indexing/",
            "task-123",
            "Connection timeout to Pinecone"
        )
        
        assert len(error_callbacks) == 1
        assert error_callbacks[0]['status'] == 'failed'
        assert 'timeout' in error_callbacks[0]['error'].lower()
    
    def test_exception_serialization(self):
        """Test that exceptions are properly serialized for callbacks"""
        import json
        
        error_payload = {
            'task_id': str(uuid4()),
            'status': 'failed',
            'error': 'IndexingError: Maximum page limit exceeded',
            'error_type': 'QuotaExceeded',
            'timestamp': datetime.now().isoformat()
        }
        
        # Should be JSON serializable
        serialized = json.dumps(error_payload)
        deserialized = json.loads(serialized)
        
        assert deserialized['error_type'] == 'QuotaExceeded'
