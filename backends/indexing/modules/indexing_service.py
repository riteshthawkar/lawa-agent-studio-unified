
import logging
import asyncio
from typing import Any, Optional, Dict
from datetime import datetime

from modules.config import CrawlerConfig, EmbeddingConfig
from modules.two_phase_processor import TwoPhaseProcessor
from modules.django_database import db_manager
from modules.webhooks import send_progress_webhook, send_webhook_callback
from modules.embedder import get_gemini_rate_limiter

logger = logging.getLogger(__name__)

async def execute_indexing_pipeline(
    task_id: str,
    crawler_config: CrawlerConfig,
    embedding_config: EmbeddingConfig,
    preloaded_embedder: Any,
    start_time: datetime,
    external_job_id: Optional[str] = None,
    callback_url: Optional[str] = None
) -> None:
    """
    Execute the core website indexing pipeline.
    This logic is shared between the API (background task) and Celery worker.

    Features fair-share rate limiting to prevent one job from monopolizing API quota.
    """
    # Get the fair share rate limiter for this job
    fair_share_limiter = get_gemini_rate_limiter()
    job_id = external_job_id or task_id

    # Use fair share rate limiting - each job gets a fair portion of the API quota
    async with fair_share_limiter.job_session(job_id) as job_limiter:
        # Set the job context on the embedder so it uses the correct rate limiter
        if hasattr(preloaded_embedder, 'set_job_context'):
            preloaded_embedder.set_job_context(job_id, job_limiter)
            logger.info(f"Job {job_id} acquired fair share rate limit")

        try:
            # Claim task and set status to processing
            # This resolves the race condition/deadlock where Django holds the lock
            claimed = await db_manager.claim_and_start_task(
                task_id,
                external_job_id,
                start_time
            )

            if not claimed:
                logger.error(f"❌ Failed to claim task {task_id} (ext: {external_job_id}). Aborting processing.")
                return

            # Send initial progress webhook - task started
            if callback_url:
                await send_progress_webhook(
                    callback_url=callback_url,
                    task_id=task_id,
                    external_job_id=external_job_id,
                    status="processing",
                    progress={"phase": "starting", "urls_collected": 0, "urls_processed": 0, "documents_indexed": 0}
                )

            # Create progress callback for the processor to use
            async def progress_callback(status: str, urls_collected: int, urls_processed: int, documents_indexed: int):
                """Callback function to send progress updates during processing."""
                if callback_url:
                    await send_progress_webhook(
                        callback_url=callback_url,
                        task_id=task_id,
                        external_job_id=external_job_id,
                        status=status,
                        progress={
                            "urls_collected": urls_collected,
                            "urls_processed": urls_processed,
                            "documents_indexed": documents_indexed
                        }
                    )

            # Initialize processor
            # preloaded_embedder is critical for performance (singleton reuse)
            processor = TwoPhaseProcessor(
                crawler_config,
                embedding_config,
                preloaded_embedder,
                db_manager=db_manager,
                task_id=task_id,
                progress_callback=progress_callback
            )

            logger.info(f"Starting indexing task {task_id} for URL: {crawler_config.start_url}")

            # Update status for Phase 1
            await db_manager.update_task_status(
                task_id,
                "collecting_urls"
            )

            # Send progress webhook - Phase 1 starting
            if callback_url:
                await send_progress_webhook(
                    callback_url=callback_url,
                    task_id=task_id,
                    external_job_id=external_job_id,
                    status="collecting_urls",
                    progress={"phase": "url_collection", "urls_collected": 0, "urls_processed": 0, "documents_indexed": 0}
                )

            # Run two-phase processing
            result = await processor.process_website()

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()

            # Update task with results
            stats = result.get("stats", {})

            # Determine status: fail if explicit failure OR if 0 docs indexed (but we tried processing)
            final_status = result.get("status", "completed")
            error_message = result.get("error", "")

            if final_status == "completed" and stats.get("total_documents_indexed", 0) == 0 and stats.get("total_urls_processed", 0) > 0:
                final_status = "failed"
                error_message = "No documents were successfully indexed (0 success rate)"
                logger.warning(f"Task {task_id} processed {stats.get('total_urls_processed')} URLs but indexed 0 docs. Marking as failed.")

            await db_manager.update_task_status(
                task_id,
                final_status,
                completed_at=datetime.now(),
                error_message=error_message if final_status == "failed" else "",
                phase1_result=result.get("phase1_result"),
                phase2_result=result.get("phase2_result"),
                urls_collected=stats.get("total_urls_collected", 0),
                urls_processed=stats.get("total_urls_processed", 0),
                documents_indexed=stats.get("total_documents_indexed", 0),
                pages_indexed=stats.get("total_urls_successful", 0)  # Bug fix: Explicitly pass pages_indexed
            )

            # Send final webhook callback if configured (with full result data)
            if callback_url:
                # Sanitize phase results to ensure JSON serializability
                phase1_sanitized = None
                if result.get("phase1_result"):
                    phase1_sanitized = {
                        k: v for k, v in result.get("phase1_result", {}).items()
                        if k != "results"  # Exclude raw CrawlResult objects
                    }

                phase2_sanitized = None
                if result.get("phase2_result"):
                    phase2_raw = result.get("phase2_result", {})
                    if isinstance(phase2_raw, dict):
                        phase2_sanitized = {
                            k: v for k, v in phase2_raw.items()
                            if k not in ("results", "crawl_results")  # Exclude non-serializable objects
                        }
                    else:
                        phase2_sanitized = str(phase2_raw)

                await send_webhook_callback(
                    callback_url=callback_url,
                    task_id=task_id,
                    external_job_id=external_job_id,
                    status=final_status,
                    result={
                        "phase1_result": phase1_sanitized,
                        "phase2_result": phase2_sanitized,
                        "stats": stats,
                        "duration": duration
                    },
                    error=error_message if final_status == "failed" else None
                )

            logger.info(f"Completed indexing task {task_id} in {duration:.2f} seconds")

        except Exception as e:
            # Handle errors
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)

            logger.error(f"Error in indexing task {task_id}: {error_msg}")

            # Update task with error
            await db_manager.update_task_status(
                task_id,
                "failed",
                completed_at=datetime.now(),
                error_message=error_msg
            )

            # Send webhook callback for failure if configured
            if callback_url:
                await send_webhook_callback(
                    callback_url=callback_url,
                    task_id=task_id,
                    external_job_id=external_job_id,
                    status="failed",
                    result={},
                    error=error_msg
                )

        finally:
            # Clear the job context from the embedder
            if hasattr(preloaded_embedder, 'clear_job_context'):
                preloaded_embedder.clear_job_context()
