#!/usr/bin/env python3
"""
FastAPI Web Application for Website Indexing Pipeline
Provides REST API endpoints for concurrent website indexing operations.
"""

import asyncio
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from urllib.parse import urlparse
import json
import logging
from dataclasses import asdict
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, BackgroundTasks, status, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl
import uvicorn
import aiohttp
from dotenv import load_dotenv
from collections import defaultdict
import time

# Load environment variables first
load_dotenv()

from modules.config import CrawlerConfig, EmbeddingConfig, get_config
from modules.two_phase_processor import TwoPhaseProcessor
from health_endpoints import router as health_router

# Load configuration
config = get_config()

# Setup Django ORM for unified data access
from django_setup import setup_django
from modules.django_database import db_manager


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define lifespan context manager for FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager for application startup and shutdown events.
    """
    logger.info("Application startup: Setting up Django ORM...")
    setup_django()
    logger.info("Django ORM setup complete.")
    
    logger.info("Starting Website Indexing API...")
    
    # Validate environment variables
    required_env_vars = ["PINECONE_API_KEY", "GEMINI_API_KEY"]
    missing_vars = []
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.warning("Some features may not work properly")
    else:
        logger.info("✅ All required environment variables are set")
    
    # Initialize database
    try:
        await db_manager.initialize()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    # Ensure required directories exist
    config.ensure_directories()
    
    # Pre-load embedding models for faster processing
    logger.info("🚀 Pre-loading embedding models...")
    try:
        from modules.embedder import GeminiDocumentEmbedder
        from modules.config import EmbeddingConfig
        
        # Create embedding config - defaults to Gemini as per config.py
        embedding_config = EmbeddingConfig()
        
        # Strictly initialize Gemini embedder
        logger.info(f"Initializing embedder with model: {embedding_config.embed_model}")
        
        embedder = GeminiDocumentEmbedder(embedding_config)
        
        # Call explicit initialization which handles BM25 and API verification with retries
        logger.info("Calling embedder.initialize()...")
        success = await embedder.initialize()
        logger.info(f"embedder.initialize() returned: {success}")
        
        if success:
            logger.info("✅ Gemini embedding models and BM25 encoder pre-loaded successfully")
            # Store embedder globally for reuse
            app.state.embedder = embedder
        else:
            logger.error("❌ Failed to initialize Gemini embedder (see logs)")
            
    except Exception as e:
        logger.error(f"❌ Failed to pre-load embedding models: {e}")
    
    logger.info("API startup completed")
    
    yield
    
    # Shutdown logic
    logger.info("Shutting down Website Indexing API...")
    
    # Mark any active tasks as cancelled
    try:
        active_tasks = await db_manager.list_tasks(status_filter=None, limit=1000)
        for task in active_tasks:
            if task["status"] in ["queued", "processing", "collecting_urls", "processing_urls"]:
                await db_manager.update_task_status(
                    task["task_id"],
                    "cancelled",
                    completed_at=datetime.now(),
                    error_message="Task cancelled due to server shutdown"
                )
        logger.info("Marked active tasks as cancelled")
    except Exception as e:
        logger.error(f"Error cancelling active tasks: {e}")
    
    # Close database connections
    try:
        await db_manager.close()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")
    
    logger.info("Application shutdown complete.")


# FastAPI app instance
app = FastAPI(
    title="Lawa Website Indexing API",
    description="API for scraping and indexing websites for RAG chatbots",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Simple in-memory rate limiter
class RateLimiter:
    """Token bucket rate limiter for API endpoints"""

    def __init__(self, requests_per_minute: int = 60, burst_size: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.tokens = defaultdict(lambda: burst_size)
        self.last_update = defaultdict(time.time)
        self.refill_rate = requests_per_minute / 60.0  # Tokens per second

    def _get_client_id(self, request: Request, authorization: Optional[str] = None) -> str:
        """Get client identifier from API key or IP address"""
        if authorization and authorization.startswith("Bearer "):
            return f"api:{authorization.split(' ', 1)[1][:32]}"
        # Fall back to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        return f"ip:{request.client.host if request.client else 'unknown'}"

    def is_allowed(self, request: Request, authorization: Optional[str] = None) -> tuple[bool, dict]:
        """Check if request is allowed under rate limit"""
        client_id = self._get_client_id(request, authorization)
        current_time = time.time()

        # Refill tokens based on time elapsed
        elapsed = current_time - self.last_update[client_id]
        self.tokens[client_id] = min(
            self.burst_size,
            self.tokens[client_id] + elapsed * self.refill_rate
        )
        self.last_update[client_id] = current_time

        # Check if we have tokens available
        if self.tokens[client_id] >= 1:
            self.tokens[client_id] -= 1
            return True, {
                "X-RateLimit-Limit": str(self.requests_per_minute),
                "X-RateLimit-Remaining": str(int(self.tokens[client_id])),
                "X-RateLimit-Reset": str(int(current_time + 60))
            }

        return False, {
            "X-RateLimit-Limit": str(self.requests_per_minute),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(current_time + (1 / self.refill_rate))),
            "Retry-After": str(int(1 / self.refill_rate))
        }


# Initialize rate limiter with configurable limits
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "60"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST_SIZE", "10"))
rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_BURST)

# Backpressure control: Limit concurrent background indexing tasks
# This prevents resource exhaustion when many requests arrive simultaneously
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_INDEXING_TASKS", "5"))
indexing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
logger.info(f"Backpressure control initialized: max {MAX_CONCURRENT_TASKS} concurrent indexing tasks")


# Add health check routes
app.include_router(health_router)

# Database manager is now imported from modules.django_database


# Pydantic models for API requests/responses
class IndexingRequest(BaseModel):
    """Simplified request model for website indexing - MVP version."""
    url: HttpUrl = Field(..., description="Website URL to index")
    max_pages: Optional[int] = Field(100, description="Maximum pages to crawl")
    site_id: Optional[str] = Field(None, description="Site identifier")
    external_job_id: Optional[str] = Field(None, description="Client idempotency key")
    allowed_domains: Optional[List[str]] = Field(None, description="Allowed domains for crawler")
    excluded_subdomains: Optional[List[str]] = Field(None, description="Excluded subdomains for crawler")
    pinecone_index: Optional[str] = Field(None, description="Target Pinecone index")
    embed_model: Optional[str] = Field(None, description="Embedding model identifier")
    streaming_mode: Optional[bool] = Field(True, description="Whether to stream results")
    use_namespaces: Optional[bool] = Field(True, description="Use Pinecone namespaces")
    namespace_prefix: Optional[str] = Field("website_domain", description="Namespace prefix")
    namespace_override: Optional[str] = Field(None, description="Explicit namespace override")
    custom_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom pipeline configuration overrides")

    # Exclusion patterns (regex, prefix, etc.)
    excluded_patterns: Optional[List[Dict[str, str]]] = Field(
        None,
        description="List of exclusion patterns (e.g., [{'pattern': '/admin', 'type': 'prefix'}])"
    )

    # Subdomain discovery configuration
    scrape_all_subdomains: Optional[bool] = Field(
        False,
        description="Auto-discover and include subdomains from crawled links"
    )
    include_subdomains: Optional[List[str]] = Field(
        None,
        description="Explicit list of subdomains to include (e.g., ['blog', 'docs'])"
    )

    # Webhook callback configuration
    callback_url: Optional[str] = Field(
        None,
        description="URL to call when indexing completes (webhook callback)"
    )


class IndexingResponse(BaseModel):
    """Response model for indexing requests."""
    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field(..., description="Task status")
    message: str = Field(..., description="Status message")
    url: str = Field(..., description="Requested URL")
    created_at: datetime = Field(..., description="Task creation timestamp")


class TaskStatus(BaseModel):
    """Task status response model."""
    task_id: str = Field(..., description="Task identifier")
    status: str = Field(..., description="Current status")
    progress: Optional[Dict[str, Any]] = Field(None, description="Progress information")
    result: Optional[Dict[str, Any]] = Field(None, description="Task result")
    error: Optional[str] = Field(None, description="Error message if failed")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    duration: Optional[float] = Field(None, description="Task duration in seconds")


class TaskList(BaseModel):
    """List of tasks response model - standardized format."""
    results: List[TaskStatus] = Field(..., description="List of tasks")
    count: int = Field(..., description="Total number of tasks")
    next: Optional[str] = Field(None, description="Next page URL")
    previous: Optional[str] = Field(None, description="Previous page URL")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(100, description="Number of items per page")


# Webhook callback sender for progress updates
async def send_progress_webhook(
    callback_url: str,
    task_id: str,
    external_job_id: Optional[str],
    status: str,
    progress: Dict[str, Any],
    max_retries: int = 3
) -> bool:
    """
    Send progress webhook to notify about intermediate task progress.
    Now includes exponential backoff retry for improved reliability.
    Returns True if callback was successful, False otherwise.
    """
    import hmac
    import hashlib

    try:
        payload = {
            "task_id": task_id,
            "external_job_id": external_job_id,
            "status": status,
            "progress": progress,
            "is_progress_update": True,
            "timestamp": datetime.now().isoformat()
        }

        # Get webhook signing secret
        webhook_secret = os.getenv("WEBHOOK_SIGNING_SECRET", "")

        # Create request body
        body = json.dumps(payload)

        # Create HMAC signature
        headers = {
            "Content-Type": "application/json",
            "X-Task-ID": task_id,
            "X-Progress-Update": "true"
        }

        if webhook_secret:
            signature = hmac.new(
                webhook_secret.encode(),
                body.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Signature"] = signature

        # Send webhook with exponential backoff retry
        async with aiohttp.ClientSession() as session:
            for attempt in range(max_retries):
                try:
                    async with session.post(
                        callback_url,
                        data=body,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status < 400:
                            logger.debug(f"Progress webhook sent: {status} - {progress}")
                            return True
                        elif response.status in [429, 500, 502, 503, 504]:
                            # Retryable errors
                            if attempt < max_retries - 1:
                                wait_time = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                                logger.debug(f"Progress webhook got {response.status}, retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                                continue
                        else:
                            logger.debug(f"Progress webhook failed: HTTP {response.status}")
                            return False

                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 0.5
                        logger.debug(f"Progress webhook timeout, retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.debug("Progress webhook timeout after retries (non-critical)")
                    return False
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 0.5
                        logger.debug(f"Progress webhook error: {e}, retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.debug(f"Progress webhook error after retries (non-critical): {e}")
                    return False
            
            return False

    except Exception as e:
        logger.debug(f"Failed to send progress webhook: {e}")
        return False


# Webhook callback sender for completion
async def send_webhook_callback(
    callback_url: str,
    task_id: str,
    external_job_id: Optional[str],
    status: str,
    result: Dict[str, Any],
    error: Optional[str] = None
) -> bool:
    """
    Send webhook callback to notify about task completion.
    Returns True if callback was successful, False otherwise.
    """
    import hmac
    import hashlib

    try:
        payload = {
            "task_id": task_id,
            "external_job_id": external_job_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }

        # Get webhook signing secret
        webhook_secret = os.getenv("WEBHOOK_SIGNING_SECRET", "")

        # Create request body
        body = json.dumps(payload)

        # Create HMAC signature
        headers = {
            "Content-Type": "application/json",
            "X-Task-ID": task_id
        }

        if webhook_secret:
            signature = hmac.new(
                webhook_secret.encode(),
                body.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Signature"] = signature

        # Send webhook with retry logic
        max_retries = 3
        retry_delay = 1

        async with aiohttp.ClientSession() as session:
            for attempt in range(max_retries):
                try:
                    async with session.post(
                        callback_url,
                        data=body,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status < 400:
                            logger.info(f"✅ Webhook callback sent successfully to {callback_url}")
                            return True
                        else:
                            logger.warning(f"Webhook callback failed (attempt {attempt + 1}/{max_retries}): HTTP {response.status}")

                except asyncio.TimeoutError:
                    logger.warning(f"Webhook callback timeout (attempt {attempt + 1}/{max_retries})")
                except Exception as e:
                    logger.warning(f"Webhook callback error (attempt {attempt + 1}/{max_retries}): {e}")

                # Wait before retrying (exponential backoff)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))

        logger.error(f"❌ Webhook callback failed after {max_retries} attempts to {callback_url}")
        return False

    except Exception as e:
        logger.error(f"❌ Failed to send webhook callback: {e}")
        return False


# Background task processing
# Background task processing (Local / BackgroundTasks)
async def process_indexing_task(
    task_id: str,
    crawler_config: CrawlerConfig,
    embedding_config: EmbeddingConfig,
    preloaded_embedder: Any,
    start_time: datetime,
    external_job_id: Optional[str] = None,
    callback_url: Optional[str] = None
) -> None:
    """
    Background task wrapper for local execution.
    Uses semaphore-based backpressure.
    """
    from modules.indexing_service import execute_indexing_pipeline
    
    # Acquire semaphore to limit concurrent processing (backpressure control)
    async with indexing_semaphore:
        logger.info(f"Task {task_id} acquired indexing slot (semaphore)")
        try:
            await execute_indexing_pipeline(
                task_id=task_id,
                crawler_config=crawler_config,
                embedding_config=embedding_config,
                preloaded_embedder=preloaded_embedder,
                start_time=start_time,
                external_job_id=external_job_id,
                callback_url=callback_url
            )
        finally:
            logger.info(f"Task {task_id} released indexing slot (semaphore)")

# API Endpoints
@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Website Indexing API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.post("/index", response_model=IndexingResponse)
async def start_indexing(
    request: IndexingRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Start a new website indexing task.
    Returns immediately with task ID, processing happens in background.
    """
    # Rate limiting check
    is_allowed, rate_headers = rate_limiter.is_allowed(http_request, authorization)
    if not is_allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded. Please try again later."},
            headers=rate_headers
        )

    # Bearer-token authentication for API security
    api_token = os.getenv("INDEXING_API_TOKEN")
    if api_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header required"
            )
        provided_token = authorization.split(" ", 1)[1]
        if provided_token != api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization token"
            )

    # Bug Fix: Ensure exclusion patterns are respected for re-indexing
    # If site_id is provided but no patterns sent (e.g. from reindex button), 
    # fetch active patterns from database.
    if request.site_id and not request.excluded_patterns:
        try:
            logger.info(f"Checking for stored exclusion patterns for site {request.site_id}...")
            stored_patterns = await db_manager.get_excluded_patterns(request.site_id)
            if stored_patterns:
                # Fix: Map 'pattern_type' from DB to 'type' expected by CrawlerConfig
                mapped_patterns = []
                for p in stored_patterns:
                    p_copy = p.copy()
                    if 'pattern_type' in p_copy:
                        p_copy['type'] = p_copy.pop('pattern_type')
                    mapped_patterns.append(p_copy)
                
                request.excluded_patterns = mapped_patterns
                logger.info(f"Applied {len(stored_patterns)} stored exclusion patterns to indexing job")
        except Exception as e:
            logger.warning(f"Failed to fetch stored exclusion patterns: {e}")

    skip_create = False
    
    # Idempotency: return existing task if external_job_id provided
    if request.external_job_id:
        try:
            existing = await db_manager.get_task_by_external_job(request.external_job_id)
            if existing:
                # Use existing task if it has a valid task_id
                if existing.get("task_id"):
                    if existing["status"] == "queued":
                        logger.info(f"Resuming queued task {existing['task_id']} for external job {request.external_job_id}")
                        task_id = existing["task_id"]
                        skip_create = True
                    else:
                        logger.info(f"Found existing active/completed task for external_job_id: {request.external_job_id}")
                        return IndexingResponse(
                            task_id=existing["task_id"],
                            status=existing["status"],
                            message="Existing task returned (idempotent)",
                            url=existing["url"],
                            created_at=datetime.fromisoformat(existing["created_at"]) if isinstance(existing.get("created_at"), str) else (existing.get("created_at") or datetime.now())
                        )
                # If existing but no task_id (stub), we will update it below IN BACKGROUND
                else:
                    logger.info(f"Found stub task for {request.external_job_id}, proceeding to assign new task_id in background")
                    skip_create = True 
        except Exception as e:
            logger.warning(f"Failed to check for existing task: {e}, continuing with new task creation")

    # Generate unique task ID if needed
    if not 'task_id' in locals() or not task_id:
        task_id = str(uuid.uuid4())
        
        # We do NOT update the DB here anymore to avoid deadlocks with the Django transaction.
        # The background task will "claim" the stub using claim_and_start_task
    
    # Generate site_id from URL if not provided
    site_id = request.site_id
    if not site_id:
        parsed_url = urlparse(str(request.url))
        # Use simple domain if possible, but Site model works best with what's stored.
        # We'll pass the full origin as default, letting DB manager handle resolution.
        site_id = f"{parsed_url.scheme}://{parsed_url.netloc}" if parsed_url.scheme else f"https://{parsed_url.netloc}"
    
    # Create task entry in database - simplified for MVP
    # Only create if we didn't find a stub. If we found a stub, background task will fix it.
    if not skip_create:
        task_data = {
            "task_id": task_id,
            "site_id": site_id,
            "external_job_id": request.external_job_id,
            "url": str(request.url),
            "status": "queued",
            "created_at": datetime.now(),
            "max_pages": request.max_pages,
            "target_namespace": request.namespace_override or f"site_{site_id}"
        }
        
        # Create task in database - this ensures the background task can claim it
        try:
            await db_manager.create_task(task_data)
        except Exception as create_err:
            logger.error(f"Failed to create task in database: {create_err}")
            # Continue anyway - background task might still work if stub exists

    # Setup Crawler Config
    crawler_config = CrawlerConfig(
        start_url=str(request.url),
        max_pages=request.max_pages,
        allowed_domains=request.allowed_domains,
        excluded_subdomains=request.excluded_subdomains,
        excluded_patterns=request.excluded_patterns,
        fetch_concurrency=5,
        download_concurrency=10,
        timeout=30,
        output_dir="data/raw",
        stealth=True,
        headless=True,
        default_delay=1.0,
        # Subdomain discovery configuration
        scrape_all_subdomains=request.scrape_all_subdomains or False,
        include_subdomains=request.include_subdomains or [],
        # Pass site_id for exclusion pattern filtering
        site_id=site_id
    )

    if request.custom_config:
        crawler_overrides = request.custom_config.get('crawler', {}) if isinstance(request.custom_config, dict) else {}
        for key, value in crawler_overrides.items():
            if value is not None and hasattr(crawler_config, key):
                setattr(crawler_config, key, value)
    
    # Compute namespace override - simplified for MVP
    computed_namespace_override = request.namespace_override
    if not computed_namespace_override and site_id:
        computed_namespace_override = f"site_{site_id}"

    base_embedding_config = EmbeddingConfig()

    if request.pinecone_index:
        base_embedding_config.pinecone_index = request.pinecone_index
    if request.embed_model:
        base_embedding_config.embed_model = request.embed_model
    if request.use_namespaces is not None:
        base_embedding_config.use_namespaces = request.use_namespaces
    if request.namespace_prefix:
        base_embedding_config.namespace_prefix = request.namespace_prefix
    base_embedding_config.namespace_override = computed_namespace_override

    embedding_overrides = {}
    if request.custom_config and isinstance(request.custom_config, dict):
        embedding_overrides = request.custom_config.get('embedding', {}) or {}

    for key, value in embedding_overrides.items():
        if value is not None and hasattr(base_embedding_config, key):
            setattr(base_embedding_config, key, value)

    embedding_config = base_embedding_config
    
    # Use pre-loaded embedder if available
    preloaded_embedder = getattr(app.state, 'embedder', None)
    if preloaded_embedder and getattr(preloaded_embedder, 'config', None):
        if preloaded_embedder.config.embed_model != embedding_config.embed_model:
            preloaded_embedder = None
            
    # MOVED: Processor initialization is now in the background task to avoid blocking API response

    # Add to background tasks with configs instead of initialized processor
    # Pass external_job_id so background task can claim the stub
    use_celery = os.getenv("USE_CELERY_WORKER", "false").lower() == "true"
    if use_celery:
        try:
            from tasks import dispatch_indexing_task
            crawler_config_dict = asdict(crawler_config)
            embedding_config_dict = asdict(embedding_config)

            # Use priority-based dispatch - routes to appropriate queue based on job size
            logger.info(f"Dispatching task {task_id} to Celery (max_pages={crawler_config.max_pages})")
            dispatch_indexing_task(
                task_id=task_id,
                crawler_config_dict=crawler_config_dict,
                embedding_config_dict=embedding_config_dict,
                start_time_iso=datetime.now().isoformat(),
                external_job_id=request.external_job_id,
                callback_url=request.callback_url
            )
        except Exception as e:
            logger.error(f"Failed to dispatch to Celery: {e}. Falling back to local.")
            background_tasks.add_task(
                process_indexing_task,
                task_id,
                crawler_config,
                embedding_config,
                preloaded_embedder,
                datetime.now(),
                request.external_job_id,
                request.callback_url
            )
    else:
        background_tasks.add_task(
            process_indexing_task,
            task_id,
            crawler_config,
            embedding_config,
            preloaded_embedder,
            datetime.now(),
            request.external_job_id,
            request.callback_url
        )

    return IndexingResponse(
        task_id=task_id,
        status="queued",
        message="Indexing task started (resolving stub in background)",
        url=str(request.url),
        created_at=datetime.now()
    )


@app.get("/tasks", response_model=TaskList)
async def list_tasks(site_id: Optional[str] = None, external_job_id: Optional[str] = None, status_filter: Optional[str] = None, limit: int = 100):
    """Get list of all tasks (active and completed)."""
    # Get active tasks from database
    active_tasks = await db_manager.list_tasks(status_filter=status_filter, site_id=site_id, external_job_id=external_job_id, limit=limit)
    active_task_list = [
        TaskStatus(
            task_id=task["task_id"],
            status=task["status"],
            progress={
                "urls_collected": task.get("urls_collected", 0),
                "urls_processed": task.get("urls_processed", 0),
                "documents_indexed": task.get("documents_indexed", 0)
            },
            result=None,
            error=task.get("error_message"),
            created_at=datetime.fromisoformat(task["created_at"]) if task["created_at"] and isinstance(task["created_at"], str) else datetime.now(),
            updated_at=datetime.fromisoformat(task["started_at"]) if task["started_at"] and isinstance(task["started_at"], str) else datetime.now(),
            duration=None
        )
        for task in active_tasks
        if task["status"] in ["queued", "processing", "collecting_urls", "processing_urls"]
    ]
    
    # Get completed tasks from database
    completed_tasks = await db_manager.list_tasks(status_filter=status_filter, site_id=site_id, external_job_id=external_job_id, limit=min(limit, 50))
    completed_task_list = [
        TaskStatus(
            task_id=task["task_id"],
            status=task["status"],
            progress={
                "urls_collected": task.get("urls_collected", 0),
                "urls_processed": task.get("urls_processed", 0),
                "documents_indexed": task.get("documents_indexed", 0)
            },
            result=None,
            error=task.get("error_message"),
            created_at=datetime.fromisoformat(task["created_at"]) if task["created_at"] and isinstance(task["created_at"], str) else datetime.now(),
            updated_at=datetime.fromisoformat(task["completed_at"]) if task["completed_at"] and isinstance(task["completed_at"], str) else datetime.now(),
            duration=None
        )
        for task in completed_tasks
        if task["status"] in ["completed", "failed", "cancelled"]
    ]
    
    # Combine all tasks for standardized response
    all_tasks = active_task_list + completed_task_list
    
    return TaskList(
        results=all_tasks,
        count=len(all_tasks),
        next=None,  # No pagination for now
        previous=None,
        page=1,
        page_size=limit
    )


@app.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Get status of a specific task."""
    # Get task from database
    task = await db_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    # Calculate duration if completed
    duration = None
    if task.get("completed_at") and task.get("started_at"):
        try:
            start = datetime.fromisoformat(task["started_at"]) if isinstance(task["started_at"], str) else task["started_at"]
            end = datetime.fromisoformat(task["completed_at"]) if isinstance(task["completed_at"], str) else task["completed_at"]
            duration = (end - start).total_seconds()
        except (ValueError, TypeError):
            duration = None
    
    return TaskStatus(
        task_id=task["task_id"],
        status=task["status"],
        progress={
            "urls_collected": task.get("urls_collected", 0),
            "urls_processed": task.get("urls_processed", 0),
            "documents_indexed": task.get("documents_indexed", 0)
        },
        result={
            "phase1_result": task.get("phase1_result"),
            "phase2_result": task.get("phase2_result")
        },
        error=task.get("error_message"),
        created_at=datetime.fromisoformat(task["created_at"]) if task.get("created_at") and isinstance(task["created_at"], str) else (task.get("created_at") if task.get("created_at") else datetime.now()),
        updated_at=datetime.fromisoformat(task["started_at"]) if task.get("started_at") and isinstance(task["started_at"], str) else (task.get("started_at") if task.get("started_at") else datetime.now()),
        duration=duration
    )


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """Cancel an active task."""
    # Check if task exists and is active
    task = await db_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    if task["status"] not in ["queued", "processing", "collecting_urls", "processing_urls"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is not active and cannot be cancelled"
        )
    
    # Mark task as cancelled
    await db_manager.update_task_status(
        task_id,
        "cancelled",
        completed_at=datetime.now(),
        error_message="Task cancelled by user"
    )
    
    logger.info(f"Cancelled task {task_id}")
    
    return {"message": f"Task {task_id} cancelled successfully"}


@app.post("/tasks/{task_id}/retry", response_model=IndexingResponse)
async def retry_task(task_id: str, background_tasks: BackgroundTasks):
    """
    Retry a failed or cancelled task.
    Resets status and restarts background processing.
    """
    # Get task from database
    task = await db_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    # Check if task is in a terminal state
    if task["status"] not in ["failed", "cancelled", "completed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is currently {task['status']} and cannot be retried"
        )
    
    # Reset task status
    await db_manager.update_task_status(
        task_id,
        "queued",
        started_at=None,
        completed_at=None,
        error_message="",
        urls_collected=0,
        urls_processed=0,
        documents_indexed=0,
        result=None
    )
    
    # Reconstruct configs for background processing
    # Note: Only persisted fields (url, max_pages) are available for retry
    # Advanced config (custom_config, etc.) is lost unless stored in DB
    crawler_config = CrawlerConfig(
        start_url=task["url"],
        max_pages=task.get("max_pages", 100),
        allowed_domains=None,
        excluded_subdomains=None,
        fetch_concurrency=5,
        download_concurrency=10,
        timeout=30,
        output_dir="data/raw",
        stealth=True,
        headless=True,
        default_delay=1.0,
        scrape_all_subdomains=False,
        include_subdomains=[]
    )

    # Setup embedding config with namespace from task
    embedding_config = EmbeddingConfig()
    if task.get("target_namespace"):
        embedding_config.namespace_override = task["target_namespace"]

    # Use pre-loaded embedder if available
    preloaded_embedder = getattr(app.state, 'embedder', None)

    # Start background task with correct parameters
    # Bug #6 fix: Use stored callback_url from the original job
    stored_callback_url = task.get("callback_url")
    
    use_celery = os.getenv("USE_CELERY_WORKER", "false").lower() == "true"
    if use_celery:
        try:
            from tasks import dispatch_indexing_task
            crawler_config_dict = asdict(crawler_config)
            embedding_config_dict = asdict(embedding_config)

            # Use priority-based dispatch for retries as well
            logger.info(f"Dispatching retried task {task_id} to Celery (max_pages={crawler_config.max_pages})")
            dispatch_indexing_task(
                task_id=task_id,
                crawler_config_dict=crawler_config_dict,
                embedding_config_dict=embedding_config_dict,
                start_time_iso=datetime.now().isoformat(),
                external_job_id=task.get("external_job_id"),
                callback_url=stored_callback_url
            )
        except Exception as e:
            logger.error(f"Failed to dispatch retry to Celery: {e}. Falling back to local.")
            background_tasks.add_task(
                process_indexing_task,
                task_id,
                crawler_config,
                embedding_config,
                preloaded_embedder,
                datetime.now(),
                task.get("external_job_id"),
                stored_callback_url
            )
    else:
        background_tasks.add_task(
            process_indexing_task,
            task_id,
            crawler_config,
            embedding_config,
            preloaded_embedder,
            datetime.now(),
            task.get("external_job_id"),
            stored_callback_url  # Use persisted callback_url for retries
        )

    logger.info(f"Retrying task {task_id}")
    
    return IndexingResponse(
        task_id=task_id,
        status="queued",
        message="Task retry initiated",
        url=task["url"],
        created_at=datetime.fromisoformat(task["created_at"]) if isinstance(task["created_at"], str) else (task.get("created_at") or datetime.now())
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        stats = await db_manager.get_task_stats()
        return {
            "status": "healthy",
            "timestamp": datetime.now(),
            "active_tasks": stats["active_tasks"],
            "completed_tasks": stats["completed_tasks"]
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(),
            "error": str(e)
        }


class SearchRequest(BaseModel):
    """Request model for knowledge base search."""
    query: str = Field(..., description="Search query text", min_length=1, max_length=1000)
    namespace: str = Field(..., description="Pinecone namespace to search in")
    top_k: int = Field(10, description="Number of results to return", ge=1, le=50)


class SearchResult(BaseModel):
    """Individual search result."""
    id: str = Field(..., description="Document ID")
    score: float = Field(..., description="Similarity score")
    title: Optional[str] = Field(None, description="Document title")
    source: Optional[str] = Field(None, description="Source URL")
    content: Optional[str] = Field(None, description="Content snippet")
    chunk_index: Optional[int] = Field(None, description="Chunk position")
    total_chunks: Optional[int] = Field(None, description="Total chunks for this document")


class SearchResponse(BaseModel):
    """Response model for search requests."""
    query: str = Field(..., description="Original search query")
    namespace: str = Field(..., description="Namespace searched")
    results: List[SearchResult] = Field(..., description="Search results")
    total_results: int = Field(..., description="Number of results returned")


@app.post("/search", response_model=SearchResponse)
async def search_knowledge_base(
    request: SearchRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Search the knowledge base for relevant content.
    Returns semantically similar documents from the specified namespace.
    """
    # Rate limiting check
    is_allowed, rate_headers = rate_limiter.is_allowed(http_request, authorization)
    if not is_allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded. Please try again later."},
            headers=rate_headers
        )

    # Bearer-token authentication for API security
    api_token = os.getenv("INDEXING_API_TOKEN")
    if api_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header required"
            )
        provided_token = authorization.split(" ", 1)[1]
        if provided_token != api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization token"
            )

    # Get the preloaded embedder
    embedder = getattr(app.state, 'embedder', None)
    if not embedder:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search service not available - embedder not initialized"
        )

    try:
        # Query for similar documents
        matches = await embedder.query_similar_documents(
            query=request.query,
            top_k=request.top_k,
            namespace=request.namespace
        )

        # Format results
        results = []
        for match in matches:
            metadata = getattr(match, 'metadata', {}) or {}
            # Try multiple content field names for compatibility
            content = (
                metadata.get('original_content') or
                metadata.get('context') or
                metadata.get('page_content') or
                metadata.get('text') or
                ''
            )
            results.append(SearchResult(
                id=match.id,
                score=float(match.score) if hasattr(match, 'score') else 0.0,
                title=metadata.get('title', ''),
                source=metadata.get('source', metadata.get('url', '')),
                content=content,
                chunk_index=metadata.get('chunk_index'),
                total_chunks=metadata.get('total_chunks')
            ))

        return SearchResponse(
            query=request.query,
            namespace=request.namespace,
            results=results,
            total_results=len(results)
        )

    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@app.get("/stats")
async def get_stats():
    """Get API statistics."""
    try:
        stats = await db_manager.get_task_stats()
        return {
            "total_tasks": stats["total_tasks"],
            "active_tasks": stats["active_tasks"],
            "completed_tasks": stats["completed_tasks"],
            "success_rate": stats["success_rate"],
            "by_status": stats["by_status"],
            "uptime": "N/A",  # Could implement uptime tracking
            "timestamp": datetime.now()
        }
    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now()
        }


class VectorDeleteRequest(BaseModel):
    """Request model for vector deletion by URL filter."""
    namespace: str = Field(..., description="Pinecone namespace")
    urls: List[str] = Field(..., description="List of URLs whose vectors should be deleted", min_length=1, max_length=100)


class VectorDeleteResponse(BaseModel):
    """Response model for vector deletion."""
    deleted_count: int = Field(..., description="Number of vectors deleted")
    namespace: str = Field(..., description="Namespace from which vectors were deleted")
    urls_processed: int = Field(..., description="Number of URLs processed")


@app.post("/vectors/delete", response_model=VectorDeleteResponse)
async def delete_vectors_by_urls(
    request: VectorDeleteRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Delete vectors from Pinecone by URL filter.
    Used for cleanup when exclusion patterns are added or pages are deleted.
    """
    # Bearer-token authentication for API security
    api_token = os.getenv("INDEXING_API_TOKEN")
    if api_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header required"
            )
        provided_token = authorization.split(" ", 1)[1]
        if provided_token != api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization token"
            )

    # Get the preloaded embedder
    embedder = getattr(app.state, 'embedder', None)
    if not embedder:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector service not available - embedder not initialized"
        )

    deleted_count = 0
    try:
        # Get Pinecone index from embedder (both DocumentEmbedder and GeminiDocumentEmbedder use 'pinecone_index')
        if hasattr(embedder, 'pinecone_index') and embedder.pinecone_index:
            # Delete vectors using metadata filter for each URL
            for url in request.urls:
                try:
                    # Pinecone delete by filter
                    embedder.pinecone_index.delete(
                        filter={"source": {"$eq": url}},  # Changed from 'url' to 'source' to match indexing metadata
                        namespace=request.namespace
                    )
                    deleted_count += 1  # Count per URL since we can't get actual vector count
                    logger.info(f"Deleted vectors for URL: {url} in namespace: {request.namespace}")
                except Exception as e:
                    error_str = str(e).lower()
                    # Expected cases: namespace doesn't exist or no vectors for this URL
                    if "namespace not found" in error_str or "404" in error_str or "not found" in error_str:
                        logger.info(f"No vectors found for URL {url} in namespace {request.namespace} (this is OK - page may not have been indexed)")
                    else:
                        # Unexpected error - log as warning
                        logger.warning(f"Failed to delete vectors for URL {url}: {e}")
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pinecone index not available"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vector deletion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector deletion failed: {str(e)}"
        )

    return VectorDeleteResponse(
        deleted_count=deleted_count,
        namespace=request.namespace,
        urls_processed=len(request.urls)
    )


class VectorNamespaceDeleteRequest(BaseModel):
    """Request model for deleting an entire namespace."""
    namespace: str = Field(..., description="Pinecone namespace to delete")


@app.delete("/vectors/namespace", response_model=Dict[str, Any])
async def delete_namespace(
    request: VectorNamespaceDeleteRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Delete an entire namespace and all its vectors from Pinecone.
    Used when a knowledge base (Site) is deleted.
    """
    # Bearer-token authentication for API security
    api_token = os.getenv("INDEXING_API_TOKEN")
    if api_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header required"
            )
        provided_token = authorization.split(" ", 1)[1]
        if provided_token != api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization token"
            )

    # Get the preloaded embedder
    embedder = getattr(app.state, 'embedder', None)
    if not embedder:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector service not available - embedder not initialized"
        )

    try:
        # Get Pinecone index from embedder
        if hasattr(embedder, 'pinecone_index') and embedder.pinecone_index:
            logger.info(f"Deleting entire namespace: {request.namespace}")
            # Delete all vectors in the namespace
            embedder.pinecone_index.delete(delete_all=True, namespace=request.namespace)
            logger.info(f"Successfully deleted namespace: {request.namespace}")
            
            return {
                "message": f"Namespace {request.namespace} deleted successfully",
                "namespace": request.namespace,
                "status": "deleted"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pinecone index not available"
            )
    except Exception as e:
        error_str = str(e).lower()
        if "namespace not found" in error_str or "404" in error_str or "not found" in error_str:
            logger.info(f"Namespace {request.namespace} not found (already deleted or never existed). Treating as success.")
            return {
                "message": f"Namespace {request.namespace} deleted successfully (not found)",
                "namespace": request.namespace,
                "status": "deleted"
            }
            
        logger.error(f"Namespace deletion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Namespace deletion failed: {str(e)}"
        )


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "error": str(exc)}
    )





if __name__ == "__main__":
    # Run the application
    uvicorn.run(
        "app:app",
        host=config.server.host,
        port=config.server.port,
        reload=True,
        log_level="info"
    )
