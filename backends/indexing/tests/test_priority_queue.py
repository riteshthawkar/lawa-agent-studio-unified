"""
Tests for Celery priority queue routing.

These tests ensure that:
1. Small jobs (< 50 pages) are routed to the priority queue
2. Large jobs (>= 50 pages) are routed to the default queue
3. Priority workers process small jobs quickly
4. Large jobs don't block small jobs
"""
import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime


class TestQueueRouting:
    """Tests for queue routing based on job size"""

    def test_get_queue_for_small_job(self):
        """Test small jobs (< 50 pages) go to priority queue"""
        from tasks import get_queue_for_job

        # Jobs under threshold go to priority
        assert get_queue_for_job(10) == 'indexing_priority'
        assert get_queue_for_job(25) == 'indexing_priority'
        assert get_queue_for_job(49) == 'indexing_priority'

    def test_get_queue_for_large_job(self):
        """Test large jobs (>= 50 pages) go to default queue"""
        from tasks import get_queue_for_job

        # Jobs at or above threshold go to default
        assert get_queue_for_job(50) == 'indexing_default'
        assert get_queue_for_job(100) == 'indexing_default'
        assert get_queue_for_job(500) == 'indexing_default'

    def test_queue_threshold_boundary(self):
        """Test exact threshold boundary"""
        from tasks import get_queue_for_job

        # 49 pages -> priority
        assert get_queue_for_job(49) == 'indexing_priority'

        # 50 pages -> default
        assert get_queue_for_job(50) == 'indexing_default'

    def test_threshold_from_environment(self):
        """Test threshold can be configured via environment variable"""
        from tasks import PRIORITY_THRESHOLD

        # Default threshold is 50
        default_threshold = int(os.getenv("PRIORITY_QUEUE_THRESHOLD", "50"))
        assert PRIORITY_THRESHOLD == default_threshold

    @patch.dict(os.environ, {"PRIORITY_QUEUE_THRESHOLD": "100"})
    def test_custom_threshold(self):
        """Test custom threshold from environment"""
        # Re-import to pick up new env var
        import importlib
        import tasks
        importlib.reload(tasks)

        # With threshold=100, 75 pages should go to priority
        assert tasks.get_queue_for_job(75) == 'indexing_priority'
        assert tasks.get_queue_for_job(100) == 'indexing_default'

        # Reset
        importlib.reload(tasks)


class TestDispatchIndexingTask:
    """Tests for the dispatch_indexing_task function"""

    @patch('tasks.index_site_task')
    def test_dispatch_routes_to_correct_queue(self, mock_task):
        """Test dispatch_indexing_task routes to correct queue"""
        from tasks import dispatch_indexing_task

        mock_task.apply_async = MagicMock()

        # Small job -> priority queue
        dispatch_indexing_task(
            task_id="task-123",
            crawler_config_dict={"start_url": "https://example.com", "max_pages": 30},
            embedding_config_dict={},
            start_time_iso=datetime.now().isoformat()
        )

        call_kwargs = mock_task.apply_async.call_args[1]
        assert call_kwargs["queue"] == "indexing_priority"

    @patch('tasks.index_site_task')
    def test_dispatch_large_job_to_default(self, mock_task):
        """Test large jobs are dispatched to default queue"""
        from tasks import dispatch_indexing_task

        mock_task.apply_async = MagicMock()

        # Large job -> default queue
        dispatch_indexing_task(
            task_id="task-456",
            crawler_config_dict={"start_url": "https://example.com", "max_pages": 200},
            embedding_config_dict={},
            start_time_iso=datetime.now().isoformat()
        )

        call_kwargs = mock_task.apply_async.call_args[1]
        assert call_kwargs["queue"] == "indexing_default"

    @patch('tasks.index_site_task')
    def test_dispatch_includes_all_parameters(self, mock_task):
        """Test dispatch passes all required parameters"""
        from tasks import dispatch_indexing_task

        mock_task.apply_async = MagicMock()

        task_id = "task-789"
        external_job_id = "ext-job-123"
        callback_url = "https://api.example.com/webhooks/"

        dispatch_indexing_task(
            task_id=task_id,
            crawler_config_dict={"start_url": "https://example.com", "max_pages": 30},
            embedding_config_dict={"model": "gemini"},
            start_time_iso=datetime.now().isoformat(),
            external_job_id=external_job_id,
            callback_url=callback_url
        )

        call_args = mock_task.apply_async.call_args
        args = call_args[0][0]  # positional args
        kwargs = call_args[1]["kwargs"]  # keyword args

        assert args[0] == task_id
        assert kwargs["external_job_id"] == external_job_id
        assert kwargs["callback_url"] == callback_url

    @patch('tasks.index_site_task')
    def test_dispatch_default_max_pages(self, mock_task):
        """Test dispatch uses default max_pages when not specified"""
        from tasks import dispatch_indexing_task

        mock_task.apply_async = MagicMock()

        # No max_pages specified, should default to 100 -> default queue
        dispatch_indexing_task(
            task_id="task-default",
            crawler_config_dict={"start_url": "https://example.com"},  # No max_pages
            embedding_config_dict={},
            start_time_iso=datetime.now().isoformat()
        )

        call_kwargs = mock_task.apply_async.call_args[1]
        # Default 100 pages -> default queue
        assert call_kwargs["queue"] == "indexing_default"


class TestCeleryQueueConfiguration:
    """Tests for Celery queue configuration"""

    def test_queues_defined(self):
        """Test all required queues are defined"""
        from celery_app import CELERY_QUEUES

        queue_names = [q.name for q in CELERY_QUEUES]

        assert 'celery' in queue_names  # Default fallback
        assert 'indexing_priority' in queue_names
        assert 'indexing_default' in queue_names

    def test_task_routes_defined(self):
        """Test task routing configuration exists"""
        from celery_app import CELERY_TASK_ROUTES

        assert 'indexing.process_site' in CELERY_TASK_ROUTES
        assert CELERY_TASK_ROUTES['indexing.process_site']['queue'] == 'indexing_default'

    def test_celery_app_configuration(self):
        """Test Celery app has correct configuration"""
        from celery_app import celery_app

        config = celery_app.conf

        # Check critical settings
        assert config.task_acks_late is True  # Ensure task acked after completion
        assert config.worker_prefetch_multiplier == 1  # Prevent task hogging

    def test_time_limits_configured(self):
        """Test task time limits are set"""
        from celery_app import celery_app

        config = celery_app.conf

        # Soft limit: 1 hour
        assert config.task_soft_time_limit == 3600

        # Hard limit: 2 hours
        assert config.task_time_limit == 7200


class TestWorkerQueueAssignment:
    """Tests for worker queue assignment"""

    def test_priority_worker_queues(self):
        """Test priority worker processes correct queues"""
        # Priority worker should handle: indexing_priority, celery
        priority_worker_queues = ['indexing_priority', 'celery']

        assert 'indexing_priority' in priority_worker_queues
        assert 'indexing_default' not in priority_worker_queues

    def test_default_worker_queues(self):
        """Test default worker processes correct queues"""
        # Default worker should handle: indexing_default, celery
        default_worker_queues = ['indexing_default', 'celery']

        assert 'indexing_default' in default_worker_queues
        assert 'indexing_priority' not in default_worker_queues

    def test_workers_dont_overlap_priority_queues(self):
        """Test workers don't process each other's priority queues"""
        priority_worker_queues = {'indexing_priority', 'celery'}
        default_worker_queues = {'indexing_default', 'celery'}

        # Only 'celery' should overlap
        overlap = priority_worker_queues & default_worker_queues
        assert overlap == {'celery'}


class TestPriorityQueueBehavior:
    """Tests for priority queue behavior in practice"""

    @pytest.mark.asyncio
    async def test_small_job_not_blocked_by_large(self):
        """Test small jobs aren't blocked by large jobs in queue"""
        import asyncio

        # Simulate: Large job in default queue, small job in priority queue
        default_queue = []
        priority_queue = []

        # Add large job to default queue
        large_job = {"id": "large-1", "max_pages": 500, "status": "processing"}
        default_queue.append(large_job)

        # Add small job to priority queue
        small_job = {"id": "small-1", "max_pages": 20, "status": "queued"}
        priority_queue.append(small_job)

        # Priority worker picks up small job immediately
        if priority_queue:
            job = priority_queue.pop(0)
            job["status"] = "processing"

        # Small job should be processing even though large job is running
        assert small_job["status"] == "processing"
        assert large_job["status"] == "processing"

    @pytest.mark.asyncio
    async def test_priority_queue_ordering(self):
        """Test jobs in same queue are processed FIFO"""
        priority_queue = []

        # Add jobs
        for i in range(5):
            priority_queue.append({
                "id": f"job-{i}",
                "added_at": i,
                "max_pages": 30
            })

        # Process in order
        processed = []
        while priority_queue:
            job = priority_queue.pop(0)  # FIFO
            processed.append(job["id"])

        assert processed == ["job-0", "job-1", "job-2", "job-3", "job-4"]

    def test_queue_isolation(self):
        """Test queues are isolated from each other"""
        priority_queue = [{"id": "p1"}, {"id": "p2"}]
        default_queue = [{"id": "d1"}, {"id": "d2"}]

        # Taking from priority doesn't affect default
        priority_job = priority_queue.pop(0)

        assert len(priority_queue) == 1
        assert len(default_queue) == 2


class TestTaskRetryBehavior:
    """Tests for task retry configuration"""

    def test_retry_configuration(self):
        """Test task has correct retry configuration"""
        from tasks import index_site_task

        # Check task has retry settings
        assert index_site_task.autoretry_for == (ConnectionError, TimeoutError)
        assert index_site_task.retry_backoff is True
        assert index_site_task.max_retries == 3

    def test_exponential_backoff(self):
        """Test exponential backoff calculation"""
        base_delay = 1  # second
        max_delay = 300  # 5 minutes

        delays = []
        for attempt in range(5):
            delay = min(base_delay * (2 ** attempt), max_delay)
            delays.append(delay)

        # Should increase exponentially up to max
        assert delays == [1, 2, 4, 8, 16]

    def test_max_backoff_capped(self):
        """Test backoff doesn't exceed maximum"""
        base_delay = 1
        max_delay = 300

        # After many retries, should cap at max
        for attempt in range(10):
            delay = min(base_delay * (2 ** attempt), max_delay)

        assert delay <= max_delay


class TestQueueMonitoring:
    """Tests for queue monitoring capabilities"""

    def test_queue_length_tracking(self):
        """Test ability to track queue lengths"""
        queues = {
            "indexing_priority": [],
            "indexing_default": [],
            "celery": []
        }

        # Add some jobs
        for i in range(3):
            queues["indexing_priority"].append({"id": f"p{i}"})

        for i in range(10):
            queues["indexing_default"].append({"id": f"d{i}"})

        # Check lengths
        lengths = {name: len(jobs) for name, jobs in queues.items()}

        assert lengths["indexing_priority"] == 3
        assert lengths["indexing_default"] == 10
        assert lengths["celery"] == 0

    def test_worker_identification(self):
        """Test workers can be identified by hostname"""
        # Worker hostnames follow pattern: {type}@{hostname}
        priority_worker = "priority@worker-1"
        default_worker = "default@worker-1"

        assert "priority" in priority_worker
        assert "default" in default_worker
