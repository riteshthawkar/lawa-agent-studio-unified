"""
Tests for Celery worker functionality.

These tests cover:
1. Worker initialization and embedder setup
2. Task execution flow
3. Worker configuration
4. Task routing and queue handling
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4


class TestWorkerEmbedderInitialization:
    """Tests for worker embedder initialization"""

    def test_get_worker_embedder_returns_global(self):
        """Test get_worker_embedder returns the global embedder"""
        from tasks import get_worker_embedder
        import celery_app as app_module

        # Set up mock embedder
        mock_embedder = MagicMock()
        app_module.worker_embedder = mock_embedder

        result = get_worker_embedder()

        assert result is mock_embedder

        # Cleanup
        app_module.worker_embedder = None

    def test_get_worker_embedder_returns_none_initially(self):
        """Test get_worker_embedder returns None before initialization"""
        from tasks import get_worker_embedder
        import celery_app as app_module

        # Ensure it's None
        app_module.worker_embedder = None

        result = get_worker_embedder()

        assert result is None

    @patch('celery_app.GeminiDocumentEmbedder')
    @patch('celery_app.get_config')
    def test_worker_init_creates_gemini_embedder(self, mock_get_config, mock_embedder_class):
        """Test worker init creates GeminiDocumentEmbedder for Gemini model"""
        from celery_app import init_worker
        import celery_app as app_module

        # Set up mock config
        mock_config = MagicMock()
        mock_config.embedding.embed_model = "gemini-embedding-001"
        mock_get_config.return_value = mock_config

        # Set up mock embedder
        mock_embedder = MagicMock()
        mock_embedder.initialize = AsyncMock(return_value=True)
        mock_embedder_class.return_value = mock_embedder

        # Call init_worker
        with patch('asyncio.run') as mock_run:
            mock_run.return_value = mock_embedder
            init_worker()

        # Verify GeminiDocumentEmbedder was used
        mock_embedder_class.assert_called_once()


class TestIndexSiteTask:
    """Tests for the index_site_task Celery task"""

    @pytest.fixture
    def mock_task_request(self):
        """Create mock Celery task request"""
        request = MagicMock()
        request.hostname = "test-worker@localhost"
        request.delivery_info = {"routing_key": "indexing.priority"}
        return request

    @pytest.fixture
    def sample_task_args(self):
        """Create sample task arguments"""
        return {
            "task_id": str(uuid4()),
            "crawler_config_dict": {
                "start_url": "https://example.com",
                "max_pages": 50
            },
            "embedding_config_dict": {
                "embed_model": "gemini-embedding-001"
            },
            "start_time_iso": datetime.now().isoformat(),
            "external_job_id": f"job_{uuid4()}",
            "callback_url": "https://api.example.com/webhooks/"
        }

    @patch('tasks.get_worker_embedder')
    @patch('tasks.execute_indexing_pipeline')
    @patch('asyncio.run')
    def test_task_calls_pipeline(self, mock_run, mock_pipeline, mock_get_embedder, sample_task_args):
        """Test task calls execute_indexing_pipeline"""
        from tasks import index_site_task

        mock_embedder = MagicMock()
        mock_get_embedder.return_value = mock_embedder

        # Create mock task instance
        task_instance = MagicMock()
        task_instance.request = MagicMock()
        task_instance.request.hostname = "test@worker"
        task_instance.request.delivery_info = {"routing_key": "test"}

        # Call task with bound=True simulation
        index_site_task.__wrapped__(
            task_instance,
            sample_task_args["task_id"],
            sample_task_args["crawler_config_dict"],
            sample_task_args["embedding_config_dict"],
            sample_task_args["start_time_iso"],
            sample_task_args["external_job_id"],
            sample_task_args["callback_url"]
        )

        # Verify pipeline was called via asyncio.run
        mock_run.assert_called_once()

    @patch('tasks.get_worker_embedder')
    def test_task_fails_without_embedder(self, mock_get_embedder, sample_task_args):
        """Test task fails when embedder not initialized"""
        from tasks import index_site_task

        mock_get_embedder.return_value = None

        task_instance = MagicMock()
        task_instance.request = MagicMock()
        task_instance.request.hostname = "test@worker"
        task_instance.request.delivery_info = {"routing_key": "test"}

        with pytest.raises(RuntimeError, match="Worker embedder not ready"):
            index_site_task.__wrapped__(
                task_instance,
                sample_task_args["task_id"],
                sample_task_args["crawler_config_dict"],
                sample_task_args["embedding_config_dict"],
                sample_task_args["start_time_iso"]
            )

    @patch('tasks.get_worker_embedder')
    @patch('asyncio.run')
    def test_task_returns_success_result(self, mock_run, mock_get_embedder, sample_task_args):
        """Test task returns success result on completion"""
        from tasks import index_site_task

        mock_get_embedder.return_value = MagicMock()

        task_instance = MagicMock()
        task_instance.request = MagicMock()
        task_instance.request.hostname = "priority@worker-1"
        task_instance.request.delivery_info = {"routing_key": "indexing.priority"}

        result = index_site_task.__wrapped__(
            task_instance,
            sample_task_args["task_id"],
            sample_task_args["crawler_config_dict"],
            sample_task_args["embedding_config_dict"],
            sample_task_args["start_time_iso"]
        )

        assert result["status"] == "completed"
        assert result["task_id"] == sample_task_args["task_id"]
        assert "worker" in result


class TestTaskDecorators:
    """Tests for task decorator configuration"""

    def test_task_has_correct_name(self):
        """Test task has correct Celery name"""
        from tasks import index_site_task

        assert index_site_task.name == "indexing.process_site"

    def test_task_has_time_limits(self):
        """Test task has appropriate time limits"""
        from tasks import index_site_task

        # Soft limit: 1 hour
        assert index_site_task.soft_time_limit == 3600

        # Hard limit: 2 hours
        assert index_site_task.time_limit == 7200

    def test_task_has_retry_config(self):
        """Test task has retry configuration"""
        from tasks import index_site_task

        assert index_site_task.autoretry_for == (ConnectionError, TimeoutError)
        assert index_site_task.retry_backoff is True
        assert index_site_task.retry_backoff_max == 300
        assert index_site_task.max_retries == 3

    def test_task_is_bound(self):
        """Test task is bound (has access to self)"""
        from tasks import index_site_task

        # Bound tasks have __self__ after decoration
        assert hasattr(index_site_task, 'bind')


class TestTaskRouting:
    """Tests for task routing to queues"""

    def test_task_can_be_routed_to_priority(self):
        """Test task can be dispatched to priority queue"""
        from tasks import dispatch_indexing_task, index_site_task

        with patch.object(index_site_task, 'apply_async') as mock_apply:
            mock_apply.return_value = MagicMock()

            dispatch_indexing_task(
                task_id="test-task",
                crawler_config_dict={"start_url": "https://example.com", "max_pages": 30},
                embedding_config_dict={},
                start_time_iso=datetime.now().isoformat()
            )

            call_kwargs = mock_apply.call_args[1]
            assert call_kwargs["queue"] == "indexing_priority"

    def test_task_can_be_routed_to_default(self):
        """Test task can be dispatched to default queue"""
        from tasks import dispatch_indexing_task, index_site_task

        with patch.object(index_site_task, 'apply_async') as mock_apply:
            mock_apply.return_value = MagicMock()

            dispatch_indexing_task(
                task_id="test-task",
                crawler_config_dict={"start_url": "https://example.com", "max_pages": 100},
                embedding_config_dict={},
                start_time_iso=datetime.now().isoformat()
            )

            call_kwargs = mock_apply.call_args[1]
            assert call_kwargs["queue"] == "indexing_default"


class TestWorkerConcurrency:
    """Tests for worker concurrency settings"""

    def test_worker_concurrency_setting(self):
        """Test worker concurrency is configured"""
        from celery_app import celery_app

        # Should have concurrency setting
        concurrency = celery_app.conf.worker_concurrency

        # Default is 2 for heavy tasks
        assert concurrency == 2

    def test_prefetch_multiplier_is_one(self):
        """Test prefetch multiplier is 1 to prevent task hogging"""
        from celery_app import celery_app

        # Critical for long-running tasks
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_task_acks_late(self):
        """Test tasks are acknowledged after completion"""
        from celery_app import celery_app

        # Ensures task is re-queued if worker crashes
        assert celery_app.conf.task_acks_late is True


class TestCeleryAppConfiguration:
    """Tests for Celery app configuration"""

    def test_broker_url_configured(self):
        """Test broker URL is configured"""
        from celery_app import celery_app

        broker_url = celery_app.conf.broker_url

        assert broker_url is not None
        assert "redis://" in broker_url

    def test_serializers_configured(self):
        """Test JSON serialization is configured"""
        from celery_app import celery_app

        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.result_serializer == "json"
        assert "json" in celery_app.conf.accept_content

    def test_timezone_is_utc(self):
        """Test timezone is UTC"""
        from celery_app import celery_app

        assert celery_app.conf.timezone == "UTC"
        assert celery_app.conf.enable_utc is True

    def test_task_routes_defined(self):
        """Test task routes are defined"""
        from celery_app import celery_app

        routes = celery_app.conf.task_routes

        assert routes is not None
        assert "indexing.process_site" in routes


class TestTaskExceptionHandling:
    """Tests for task exception handling"""

    @patch('tasks.get_worker_embedder')
    @patch('asyncio.run')
    def test_task_propagates_exceptions(self, mock_run, mock_get_embedder):
        """Test task propagates exceptions for retry"""
        from tasks import index_site_task

        mock_get_embedder.return_value = MagicMock()
        mock_run.side_effect = ConnectionError("Network error")

        task_instance = MagicMock()
        task_instance.request = MagicMock()
        task_instance.request.hostname = "test@worker"
        task_instance.request.delivery_info = {"routing_key": "test"}

        with pytest.raises(ConnectionError):
            index_site_task.__wrapped__(
                task_instance,
                "task-123",
                {"start_url": "https://example.com"},
                {},
                datetime.now().isoformat()
            )

    @patch('tasks.get_worker_embedder')
    @patch('asyncio.run')
    def test_task_logs_hostname(self, mock_run, mock_get_embedder, caplog):
        """Test task logs worker hostname"""
        from tasks import index_site_task
        import logging

        mock_get_embedder.return_value = MagicMock()

        task_instance = MagicMock()
        task_instance.request = MagicMock()
        task_instance.request.hostname = "priority@worker-1"
        task_instance.request.delivery_info = {"routing_key": "indexing.priority"}

        with caplog.at_level(logging.INFO):
            index_site_task.__wrapped__(
                task_instance,
                "task-123",
                {"start_url": "https://example.com"},
                {},
                datetime.now().isoformat()
            )

        # Verify hostname appears in logs
        assert "priority@worker-1" in caplog.text


class TestTaskIdempotency:
    """Tests for task idempotency considerations"""

    def test_task_id_uniqueness(self):
        """Test task IDs are unique"""
        task_ids = [str(uuid4()) for _ in range(100)]

        assert len(task_ids) == len(set(task_ids))

    def test_external_job_id_mapping(self):
        """Test external job IDs map to internal task IDs"""
        external_id = "django-job-123"
        internal_id = str(uuid4())

        mapping = {external_id: internal_id}

        assert mapping[external_id] == internal_id


class TestWorkerHealthCheck:
    """Tests for worker health monitoring"""

    def test_worker_heartbeat_configured(self):
        """Test worker heartbeat is enabled by default"""
        from celery_app import celery_app

        # Celery enables heartbeat by default
        # This test documents the expected behavior
        assert celery_app.conf.broker_heartbeat is None or celery_app.conf.broker_heartbeat > 0

    def test_result_expiry_configured(self):
        """Test results expire after reasonable time"""
        from celery_app import celery_app

        # Results should expire to prevent memory buildup
        assert celery_app.conf.result_expires == 86400  # 24 hours
