
import os
import logging
from celery import Celery
from kombu import Queue, Exchange
import sys
from pathlib import Path

# Add backend to path immediately to allow Django settings to load
# This matches the volume mount /app/backend in Docker
backend_path = Path(__file__).resolve().parent.parent / "core"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from celery.signals import worker_process_init
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Celery app
# Broker URL from env or default to localhost
broker_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("website_indexing", broker=broker_url, include=['tasks'])

# Define exchanges and queues for priority-based routing
default_exchange = Exchange('indexing', type='direct')

# Priority queues configuration
# - indexing_priority: Small jobs (< 50 pages) - processed quickly
# - indexing_default: Large jobs (>= 50 pages) - may take longer
CELERY_QUEUES = (
    Queue('celery', default_exchange, routing_key='celery'),  # Default fallback
    Queue('indexing_priority', default_exchange, routing_key='indexing.priority'),
    Queue('indexing_default', default_exchange, routing_key='indexing.default'),
)

# Task routing based on job size (configured in app.py when dispatching)
CELERY_TASK_ROUTES = {
    'indexing.process_site': {
        'queue': 'indexing_default',  # Default queue, overridden at dispatch time
        'routing_key': 'indexing.default',
    },
    'indexing.process_site_priority': {
        'queue': 'indexing_priority',
        'routing_key': 'indexing.priority',
    },
}

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Worker configuration
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "2")),  # Default low concurrency as tasks are heavy
    worker_prefetch_multiplier=1,  # Critical for long running tasks to prevent hogging
    task_acks_late=True,  # Ensure task is acked only after completion
    # Priority queue configuration
    task_queues=CELERY_QUEUES,
    task_routes=CELERY_TASK_ROUTES,
    task_default_queue='celery',
    task_default_exchange='indexing',
    task_default_routing_key='celery',
    # Task time limits (prevent runaway tasks)
    task_soft_time_limit=3600,  # 1 hour soft limit (sends SoftTimeLimitExceeded)
    task_time_limit=7200,  # 2 hour hard limit (kills task)
    # Result backend (optional - for tracking)
    result_expires=86400,  # Results expire after 24 hours
)

# Global embedder instance for the worker process
worker_embedder = None

@worker_process_init.connect
def init_worker(**kwargs):
    """Initialize resources when a worker process starts."""
    global worker_embedder
    try:
        logger.info("Initializing Celery worker resources (Embedder)...")
        from modules.embedder import DocumentEmbedder, GeminiDocumentEmbedder
        from modules.config import get_config
        import asyncio

        config = get_config()
        embed_config = config.embedding
        
        # Initialize embedder logic
        # We need to run the async initialization synchronously here
        # But DocumentEmbedder.__init__ is synchronous for setup, 
        # only .initialize() (loading models) is async.
        
        if "gemini" in embed_config.embed_model:
             embedder = GeminiDocumentEmbedder(embed_config)
        else:
             embedder = DocumentEmbedder(embed_config)
        
        # Run async initialization
        # Note: asyncio.run() creates a new event loop. 
        # Verify if this conflicts with Celery's loop if mostly sync.
        # Celery workers are usually sync (prefork).
        
        async def _init_embedder():
            success = await embedder.initialize()
            if success:
                logger.info("✅ Worker embedder initialized successfully")
                return embedder
            else:
                logger.error("❌ Worker embedder initialization failed")
                return None

        worker_embedder = asyncio.run(_init_embedder())
        
        logger.info("Celery worker initialization completed")
        
    except Exception as e:
        logger.error(f"Failed to initialize worker resources: {e}")
