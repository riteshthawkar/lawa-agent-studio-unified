
import os
import json
import hmac
import hashlib
import aiohttp
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

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
