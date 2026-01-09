import asyncio
import os
import sys
import logging
import uuid
from datetime import datetime
import json
import redis
from celery.result import AsyncResult

# Add module path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celery_app import celery_app
from modules.config import CrawlerConfig, EmbeddingConfig

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("verify_queue")

def verify_redis_connection():
    """Verify we can connect to Redis."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6380/0")
    logger.info(f"Connecting to Redis at {redis_url}...")
    try:
        r = redis.from_url(redis_url)
        r.ping()
        logger.info("✅ Redis connection successful")
        return r
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        return None

def test_task_submission():
    """Test submitting a task to the queue."""
    logger.info("Testing task submission to Celery queue...")
    
    # Mock task data
    task_id = str(uuid.uuid4())
    crawler_config = CrawlerConfig(start_url="https://example.com", max_pages=1).to_dict() if hasattr(CrawlerConfig, 'to_dict') else CrawlerConfig(start_url="https://example.com", max_pages=1).__dict__
    embedding_config = EmbeddingConfig().to_dict() if hasattr(EmbeddingConfig, 'to_dict') else EmbeddingConfig().__dict__
    
    try:
        from tasks import index_site_task
        
        # We use .apply_async to specify the queue if needed, or just .delay
        # Using a mock external_job_id
        external_job_id = f"test_job_{task_id}"
        
        logger.info(f"Dispatching task {task_id}...")
        result = index_site_task.apply_async(
            kwargs={
                "task_id": task_id,
                "crawler_config_dict": crawler_config,
                "embedding_config_dict": embedding_config,
                "start_time_iso": datetime.now().isoformat(),
                "external_job_id": external_job_id
            }
        )
        
        logger.info(f"✅ Task dispatched. Celery Task ID: {result.id}")
        return result.id, task_id
        
    except Exception as e:
        logger.error(f"❌ Failed to dispatch task: {e}")
        return None, None

def check_queue_status(redis_client):
    """Check if task is in Redis queue."""
    try:
        # Default celery queue key is 'celery'
        queue_len = redis_client.llen("celery")
        logger.info(f"Current tasks in 'celery' queue: {queue_len}")
        return queue_len
    except Exception as e:
        logger.error(f"Failed to check queue length: {e}")
        return 0

if __name__ == "__main__":
    logger.info("Starting Queue Flow Verification")
    
    # 1. Check Redis
    r = verify_redis_connection()
    if not r:
        sys.exit(1)
        
    # 2. Check Queue before
    initial_len = check_queue_status(r)
    
    # 3. Submit Task
    celery_id, task_id = test_task_submission()
    if not celery_id:
        sys.exit(1)
        
    # 4. Check Queue after (should be +1 if worker is NOT running, or 0 if worker picked it up immediately)
    # Since we might be running this while worker is off (to verify queueing), or on.
    # We'll just report the status.
    import time
    time.sleep(1)
    new_len = check_queue_status(r)
    
    logger.info(f"Queue length changed from {initial_len} to {new_len}")
    
    if new_len > initial_len:
         logger.info("✅ Task successfully queued (Worker might be down or busy)")
    elif new_len == initial_len:
         # Could be picked up immediately?
         logger.info("ℹ️ Queue length unchanged. Task might have been picked up immediately by a running worker.")
    
    logger.info("Verification script completed.")
