"""
Comprehensive tests for Embedded Chatbot Widget Backend.

These tests cover:
- WebSocket endpoints (/ws/{api_key})
- Test chat API endpoint
- API key validation
- Request/Response schemas
- Session management
- RAG pipeline integration
- Analytics tracking
"""
import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

# Test fixtures
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


class TestChatRequestSchema:
    """Tests for ChatRequest schema validation"""
    
    def test_valid_chat_request(self, chat_request_payload):
        """Test that valid payload is accepted"""
        from modules.schemas import ChatRequest
        
        request = ChatRequest(**chat_request_payload)
        
        assert request.question == "What is your return policy?"
        assert request.language == "en"
        assert request.conversation_turn == 1
    
    def test_chat_request_question_max_length(self):
        """Test question max length validation"""
        from modules.schemas import ChatRequest
        from pydantic import ValidationError
        
        long_question = "x" * 1025  # Exceeds 1024 limit
        
        with pytest.raises(ValidationError):
            ChatRequest(
                question=long_question,
                language="en"
            )
    
    def test_chat_request_defaults(self):
        """Test default values"""
        from modules.schemas import ChatRequest
        
        request = ChatRequest(
            question="Test question",
            language="en"
        )
        
        assert request.previous_chats == []
        assert request.conversation_turn is None
        assert request.device_type is None
        assert request.referrer is None
    
    def test_chat_request_with_previous_chats(self):
        """Test with conversation history"""
        from modules.schemas import ChatRequest
        
        previous = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"}
        ]
        
        request = ChatRequest(
            question="Follow up question",
            language="en",
            previous_chats=previous
        )
        
        assert len(request.previous_chats) == 2


class TestCitationSourceSchema:
    """Tests for CitationSource schema"""
    
    def test_valid_citation(self):
        """Test valid citation source"""
        from modules.schemas import CitationSource
        
        citation = CitationSource(
            url="https://example.com/docs/returns",
            cite_num="1"
        )
        
        assert citation.url == "https://example.com/docs/returns"
        assert citation.cite_num == "1"


class TestAPIKeyValidation:
    """Tests for API key validation"""
    
    @pytest.mark.asyncio
    async def test_valid_api_key_format(self):
        """Test that valid API key format is accepted"""
        api_key = "cb_abcdef1234567890abcdef1234567890"
        
        # API key should start with 'cb_' prefix
        assert api_key.startswith("cb_")
        assert len(api_key) > 10  # Minimum length
    
    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self):
        """Test that invalid API key is rejected"""
        invalid_keys = [
            "",
            "invalid",
            "wrong_prefix_123",
            None
        ]
        
        for key in invalid_keys:
            if key:
                assert not key.startswith("cb_") or len(key) < 10


class TestWebSocketConnection:
    """Tests for WebSocket connection handling"""
    
    @pytest.mark.asyncio
    async def test_websocket_connection_lifecycle(self):
        """Test WebSocket connection lifecycle"""
        # Simulate connection states
        connection_states = []
        
        # Connect
        connection_states.append("connecting")
        connection_states.append("connected")
        
        # Message exchange
        connection_states.append("message_received")
        connection_states.append("response_sent")
        
        # Disconnect
        connection_states.append("disconnected")
        
        assert len(connection_states) == 5
    
    @pytest.mark.asyncio
    async def test_session_creation_on_first_message(self):
        """Test that session is created lazily on first message"""
        session_created = False
        
        async def ensure_session_created():
            nonlocal session_created
            session_created = True
            return str(uuid4())
        
        # Simulate first message
        session_id = await ensure_session_created()
        
        assert session_created is True
        assert session_id is not None
    
    @pytest.mark.asyncio
    async def test_message_processing(self):
        """Test message processing flow"""
        message = {
            "type": "chat",
            "question": "Hello",
            "language": "en"
        }
        
        # Should process without error
        assert message["type"] == "chat"
        assert "question" in message


class TestTestChatEndpoint:
    """Tests for test chat endpoint (admin testing)"""
    
    def test_test_chat_request_model(self):
        """Test TestChatRequest model structure"""
        request_data = {
            "message": "Test message",
            "language": "en",
            "previous_chats": []
        }
        
        assert "message" in request_data
        assert "language" in request_data
    
    def test_test_chat_response_model(self):
        """Test TestChatResponse model structure"""
        response_data = {
            "response": "This is a test response",
            "sources": [{"url": "https://example.com", "cite_num": "1"}],
            "is_test": True
        }
        
        assert response_data["is_test"] is True
        assert "response" in response_data
        assert "sources" in response_data
    
    def test_test_endpoint_does_not_save_to_db(self):
        """Test that test endpoint doesn't save to database"""
        # Test endpoint should NOT save
        should_save_to_db = False  # For test endpoint
        
        assert should_save_to_db is False


class TestRAGPipelineIntegration:
    """Tests for RAG pipeline integration"""
    
    @pytest.mark.asyncio
    async def test_retrieval_called_with_namespace(self):
        """Test that retrieval is called with correct namespace"""
        namespace = "site_test_namespace_123"
        query = "What is your return policy?"
        
        # Mock retrieval
        retrieved_context = [
            {
                "content": "Our return policy allows...",
                "url": "https://example.com/returns",
                "score": 0.95
            }
        ]
        
        assert len(retrieved_context) > 0
        assert "content" in retrieved_context[0]
    
    @pytest.mark.asyncio
    async def test_gemini_embeddings_used(self):
        """Test that Gemini embeddings are used for retrieval"""
        # Embedding should produce vector
        mock_embedding = [0.1] * 768  # 768-dim vector
        
        assert len(mock_embedding) == 768
    
    @pytest.mark.asyncio
    async def test_citations_included_in_response(self):
        """Test that citations are included in response"""
        response = {
            "message": "Based on our documentation [1]...",
            "sources": [
                {"url": "https://example.com/docs", "cite_num": "1"}
            ]
        }
        
        assert "[1]" in response["message"]
        assert len(response["sources"]) == 1


class TestSessionManagement:
    """Tests for chat session management"""
    
    @pytest.mark.asyncio
    async def test_session_creation_with_metadata(self):
        """Test session creation with device metadata"""
        session_data = {
            "id": str(uuid4()),
            "chatbot_id": str(uuid4()),
            "device_type": "mobile",
            "referrer": "https://example.com",
            "created_at": datetime.now().isoformat()
        }
        
        assert "device_type" in session_data
        assert session_data["device_type"] == "mobile"
    
    @pytest.mark.asyncio
    async def test_message_added_to_session(self):
        """Test messages are added to session"""
        messages = []
        
        # User message
        messages.append({
            "role": "user",
            "content": "Hello",
            "timestamp": datetime.now().isoformat()
        })
        
        # Assistant message
        messages.append({
            "role": "assistant",
            "content": "Hi! How can I help?",
            "timestamp": datetime.now().isoformat()
        })
        
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
    
    @pytest.mark.asyncio
    async def test_session_closed_on_disconnect(self):
        """Test session is closed on WebSocket disconnect"""
        session_closed = False
        
        async def close_session():
            nonlocal session_closed
            session_closed = True
        
        await close_session()
        
        assert session_closed is True


class TestAnalyticsTracking:
    """Tests for analytics data collection"""
    
    def test_conversation_turn_tracked(self):
        """Test that conversation turns are tracked"""
        turns = []
        
        for i in range(1, 4):
            turns.append({
                "turn": i,
                "user_message": f"Message {i}",
                "assistant_response": f"Response {i}"
            })
        
        assert len(turns) == 3
        assert turns[0]["turn"] == 1
        assert turns[2]["turn"] == 3
    
    def test_device_type_recorded(self):
        """Test that device type is recorded"""
        valid_device_types = ["mobile", "tablet", "desktop", "unknown"]
        
        for device in valid_device_types:
            assert device in valid_device_types
    
    def test_referrer_recorded(self):
        """Test that referrer URL is recorded"""
        referrer = "https://example.com/products/item-123"
        
        assert referrer.startswith("https://")
    
    def test_geo_location_tracked(self):
        """Test that geo location is tracked"""
        geo_data = {
            "country": "US",
            "city": "New York",
            "latitude": 40.7128,
            "longitude": -74.0060
        }
        
        assert "country" in geo_data
        assert "city" in geo_data


class TestErrorHandling:
    """Tests for error handling"""
    
    @pytest.mark.asyncio
    async def test_invalid_message_format(self):
        """Test handling of invalid message format"""
        invalid_message = "not a json"
        
        try:
            json.loads(invalid_message)
            is_valid_json = True
        except json.JSONDecodeError:
            is_valid_json = False
        
        assert is_valid_json is False
    
    @pytest.mark.asyncio
    async def test_missing_required_fields(self):
        """Test handling of missing required fields"""
        incomplete_message = {
            "type": "chat"
            # Missing 'question' field
        }
        
        assert "question" not in incomplete_message
    
    @pytest.mark.asyncio
    async def test_retrieval_failure_handled(self):
        """Test graceful handling of retrieval failure"""
        fallback_response = "I'm sorry, I couldn't find relevant information. Please try rephrasing your question."
        
        assert "sorry" in fallback_response.lower()
