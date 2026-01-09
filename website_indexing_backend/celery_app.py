
import os
import logging
from celery import Celery
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
celery_app = Celery("website_indexing", broker=broker_url)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Worker configuration
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "2")), # Default low concurrency as tasks are heavy
    worker_prefetch_multiplier=1,  # Critical for long running tasks to prevent hogging
    task_acks_late=True, # Ensure task is acked only after completion
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
