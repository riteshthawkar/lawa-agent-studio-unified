
import asyncio
import os
from datetime import datetime
from typing import Optional, Dict, Any
import logging

from celery_app import celery_app
from modules.config import CrawlerConfig, EmbeddingConfig
from modules.indexing_service import execute_indexing_pipeline

logger = logging.getLogger(__name__)

# Priority queue threshold - jobs with max_pages below this go to priority queue
PRIORITY_THRESHOLD = int(os.getenv("PRIORITY_QUEUE_THRESHOLD", "50"))


def get_worker_embedder():
    """Get the worker embedder dynamically at runtime.

    This is necessary because the embedder is initialized by the worker_process_init
    signal handler AFTER the tasks module is imported. If we import it at module level,
    we get the initial None value instead of the initialized embedder.
    """
    import celery_app as app_module
    return app_module.worker_embedder


def get_queue_for_job(max_pages: int) -> str:
    """
    Determine which queue a job should be routed to based on its size.

    Args:
        max_pages: Maximum pages to index

    Returns:
        Queue name ('indexing_priority' or 'indexing_default')
    """
    if max_pages < PRIORITY_THRESHOLD:
        return 'indexing_priority'
    return 'indexing_default'


def dispatch_indexing_task(
    task_id: str,
    crawler_config_dict: Dict[str, Any],
    embedding_config_dict: Dict[str, Any],
    start_time_iso: str,
    external_job_id: Optional[str] = None,
    callback_url: Optional[str] = None
):
    """
    Dispatch an indexing task to the appropriate queue based on job size.

    This is the main entry point for dispatching tasks with priority routing.
    """
    max_pages = crawler_config_dict.get('max_pages', 100)
    queue = get_queue_for_job(max_pages)

    logger.info(f"Dispatching task {task_id} to queue '{queue}' (max_pages={max_pages})")

    # Dispatch to the appropriate queue
    return index_site_task.apply_async(
        args=[task_id, crawler_config_dict, embedding_config_dict, start_time_iso],
        kwargs={'external_job_id': external_job_id, 'callback_url': callback_url},
        queue=queue
    )


@celery_app.task(bind=True, name="indexing.process_site",
                 soft_time_limit=3600, time_limit=7200,
                 autoretry_for=(ConnectionError, TimeoutError),
                 retry_backoff=True, retry_backoff_max=300, max_retries=3)
def index_site_task(
    self,
    task_id: str,
    crawler_config_dict: Dict[str, Any],
    embedding_config_dict: Dict[str, Any],
    start_time_iso: str,
    external_job_id: Optional[str] = None,
    callback_url: Optional[str] = None
):
    """
    Celery task to run the indexing pipeline.
    Wraps the async execution logic.

    Features:
    - Auto-retry on connection/timeout errors with exponential backoff
    - Soft time limit of 1 hour (raises SoftTimeLimitExceeded)
    - Hard time limit of 2 hours (kills task)
    """
    worker_hostname = self.request.hostname or 'unknown'
    queue_name = self.request.delivery_info.get('routing_key', 'unknown') if self.request.delivery_info else 'unknown'

    logger.info(f"[{worker_hostname}] Received task {task_id} from queue '{queue_name}'")

    try:
        # Reconstruct configs
        crawler_config = CrawlerConfig(**crawler_config_dict)
        embedding_config = EmbeddingConfig(**embedding_config_dict)

        start_time = datetime.fromisoformat(start_time_iso)

        # Get embedder dynamically at runtime
        embedder = get_worker_embedder()

        # Check embedder
        if not embedder:
            logger.error("Worker embedder not initialized! Cannot proceed.")
            raise RuntimeError("Worker embedder not ready")

        # Log job details for monitoring
        logger.info(f"[{worker_hostname}] Starting indexing: url={crawler_config.start_url}, "
                   f"max_pages={crawler_config.max_pages}, external_job_id={external_job_id}")

        # Run async pipeline synchronously
        asyncio.run(execute_indexing_pipeline(
            task_id=task_id,
            crawler_config=crawler_config,
            embedding_config=embedding_config,
            preloaded_embedder=embedder,
            start_time=start_time,
            external_job_id=external_job_id,
            callback_url=callback_url
        ))

        logger.info(f"[{worker_hostname}] Task {task_id} completed successfully")
        return {"status": "completed", "task_id": task_id, "worker": worker_hostname}

    except Exception as e:
        logger.error(f"[{worker_hostname}] Task {task_id} failed: {e}")
        # Task failure will be handled by execute_indexing_pipeline updating DB/Webhooks
        # if it got that far. If not, we might want to ensure DB is updated here.
        raise e
