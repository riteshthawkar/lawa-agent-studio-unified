"""
pytest configuration and fixtures for EMBEDDED_CHATBOT tests.
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_manager():
    """Mock database manager"""
    manager = MagicMock()
    manager.create_task = AsyncMock(return_value={"task_id": str(uuid4())})
    manager.update_task_status = AsyncMock(return_value=True)
    manager.get_task = AsyncMock(return_value={"task_id": "t1", "status": "completed"})
    return manager


@pytest.fixture
def mock_chatbot_config():
    """Mock chatbot configuration from Django"""
    return {
        "api_key": "cb_test_api_key_123456789012345678901234",
        "site_id": str(uuid4()),
        "name": "Test Bot",
        "namespace": "site_test_namespace_123",
        "config": {
            "model_provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.7,
            "system_prompt": "You are a helpful assistant."
        },
        "status": "active"
    }


@pytest.fixture
def chat_request_payload():
    """Valid chat request payload"""
    return {
        "question": "What is your return policy?",
        "language": "en",
        "previous_chats": [],
        "conversation_turn": 1,
        "device_type": "desktop",
        "referrer": "https://example.com/products"
    }


@pytest.fixture
def mock_websocket():
    """Mock WebSocket connection"""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def mock_retrieval_response():
    """Mock retrieval response from vector DB"""
    return [
        {
            "content": "Our return policy allows returns within 30 days.",
            "url": "https://example.com/returns",
            "score": 0.95
        },
        {
            "content": "Items must be in original condition.",
            "url": "https://example.com/conditions",
            "score": 0.85
        }
    ]
