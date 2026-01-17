import pytest
from unittest.mock import AsyncMock, patch
from modules.webhooks import send_webhook_callback, send_progress_webhook

@pytest.mark.asyncio
async def test_send_webhook_callback_success():
    """Test successful webhook callback"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        # Mock response context manager
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await send_webhook_callback(
            callback_url="http://callback.com",
            task_id="t1",
            external_job_id="j1",
            status="completed",
            result={"foo": "bar"}
        )
        
        assert result is True
        assert mock_post.called
        # Check payload
        call_kwargs = mock_post.call_args[1]
        assert "X-Task-ID" in call_kwargs["headers"]

@pytest.mark.asyncio
async def test_send_webhook_retry_logic():
    """Test retry logic on failure"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        # Mock setup to fail twice then succeed
        mock_response_fail = AsyncMock()
        mock_response_fail.status = 500
        
        mock_response_success = AsyncMock()
        mock_response_success.status = 200
        
        mock_post.return_value.__aenter__.side_effect = [
            mock_response_fail,
            mock_response_fail,
            mock_response_success
        ]
        
        # Patch sleep to speed up test
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await send_webhook_callback(
                callback_url="http://callback.com",
                task_id="t1",
                external_job_id="j1",
                status="completed",
                result={}
            )
        
        assert result is True
        assert mock_post.call_count == 3

@pytest.mark.asyncio
async def test_progress_webhook():
    """Test progress webhook invocation"""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await send_progress_webhook(
            callback_url="http://callback.com",
            task_id="t1",
            external_job_id="j1",
            status="processing",
            progress={"percent": 50}
        )
        
        assert result is True
