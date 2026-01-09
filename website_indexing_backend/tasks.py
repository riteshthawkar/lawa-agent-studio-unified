
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
import logging

from celery_app import celery_app, worker_embedder
from modules.config import CrawlerConfig, EmbeddingConfig
from modules.indexing_service import execute_indexing_pipeline

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="indexing.process_site")
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
    """
    logger.info(f"Received Celery task for {task_id}")
    
    # Reconstruct config objects from dicts (Celery passes JSON)
    # We need to handle this manually since Dataclasses aren't purely JSON serializable 
    # if they have complex types, but our configs are mostly simple types.
    # However, create_indexing_req in app.py creates Pydantic which converts to dict.
    
    try:
        # Reconstruct configs
        crawler_config = CrawlerConfig(**crawler_config_dict)
        embedding_config = EmbeddingConfig(**embedding_config_dict)
        
        start_time = datetime.fromisoformat(start_time_iso)
        
        # Check embedder
        if not worker_embedder:
            logger.error("Worker embedder not initialized! Cannot proceed.")
            # We could try to initialize here as fallback?
            # But let's fail fast for now.
            raise RuntimeError("Worker embedder not ready")
            
        # Run async pipeline synchronously
        asyncio.run(execute_indexing_pipeline(
            task_id=task_id,
            crawler_config=crawler_config,
            embedding_config=embedding_config,
            preloaded_embedder=worker_embedder,
            start_time=start_time,
            external_job_id=external_job_id,
            callback_url=callback_url
        ))
        
        logger.info(f"Celery task {task_id} completed")
        return {"status": "completed", "task_id": task_id}
        
    except Exception as e:
        logger.error(f"Celery task failed: {e}")
        # Task failure will be handled by execute_indexing_pipeline updating DB/Webhooks 
        # if it got that far. If not, we might want to ensure DB is updated here.
        raise e
