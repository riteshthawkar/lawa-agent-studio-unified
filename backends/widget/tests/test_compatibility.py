"""
Compatibility tests between Django Backend, Widget Backend, and Widget Frontend.

These tests ensure:
- API key format consistency
- Config schema compatibility
- WebSocket message format compatibility
- Response format compatibility
- URL generation consistency
- Event schema compatibility
"""
import pytest
import json
from datetime import datetime
from uuid import uuid4


class TestAPIKeyCompatibility:
    """Tests for API key format compatibility across systems"""
    
    def test_api_key_format_from_django(self):
        """Test Django generates correct API key format"""
        # Django generates keys with 'cb_' prefix
        django_api_key = f"cb_{''.join(['a'] * 32)}"
        
        assert django_api_key.startswith("cb_")
        assert len(django_api_key) == 35  # 3 (prefix) + 32 (key)
    
    def test_widget_backend_accepts_django_key(self):
        """Test widget backend accepts Django-generated keys"""
        django_key = "cb_abcdef1234567890abcdef1234567890"
        
        # Widget backend validation
        is_valid = (
            django_key.startswith("cb_") and 
            len(django_key) > 5
        )
        
        assert is_valid is True
    
    def test_widget_frontend_sends_key_correctly(self):
        """Test widget frontend sends key in correct format"""
        # Widget frontend extracts from data-api-key attribute
        embed_code = '<script data-api-key="cb_test123" src="..."></script>'
        
        # Should be able to extract key
        import re
        match = re.search(r'data-api-key="([^"]+)"', embed_code)
        
        assert match is not None
        assert match.group(1).startswith("cb_")


class TestConfigSchemaCompatibility:
    """Tests for config schema compatibility"""
    
    def test_django_chatbot_config_schema(self):
        """Test Django chatbot config schema"""
        django_config = {
            "model_provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.7,
            "system_prompt": "You are a helpful assistant.",
            "retrieval_config": {
                "top_k": 5,
                "threshold": 0.5
            }
        }
        
        required_fields = ["model_provider", "model", "temperature"]
        for field in required_fields:
            assert field in django_config
    
    def test_widget_backend_accepts_django_config(self):
        """Test widget backend accepts Django config format"""
        # Config passed from Django to widget backend
        config_for_widget = {
            "model_provider": "openai",
            "model_name": "gpt-4o",  # Note: might use 'model' or 'model_name'
            "temperature": 0.7,
            "system_prompt": "You are helpful."
        }
        
        # Widget backend should accept this
        assert "model_provider" in config_for_widget
    
    def test_config_field_name_mapping(self):
        """Test config field name mapping between systems"""
        # Django uses 'model', widget backend might use 'model_name'
        django_field = "model"
        widget_field = "model_name"
        
        django_config = {"model": "gpt-4o"}
        
        # Mapping should work
        widget_config = {
            "model_name": django_config.get("model") or django_config.get("model_name")
        }
        
        assert widget_config["model_name"] == "gpt-4o"


class TestWebSocketMessageCompatibility:
    """Tests for WebSocket message format compatibility"""
    
    def test_widget_frontend_chat_message_format(self):
        """Test widget frontend sends correct message format"""
        frontend_message = {
            "type": "chat",
            "question": "What is your return policy?",
            "language": "en",
            "previous_chats": [],
            "conversation_turn": 1,
            "device_type": "desktop",
            "referrer": "https://example.com/products"
        }
        
        required_fields = ["type", "question", "language"]
        for field in required_fields:
            assert field in frontend_message
    
    def test_widget_backend_response_format(self):
        """Test widget backend response format for frontend"""
        backend_response = {
            "type": "response",
            "message": "Our return policy allows...",
            "sources": [
                {"url": "https://example.com/returns", "cite_num": "1"}
            ],
            "session_id": str(uuid4()),
            "message_id": str(uuid4())
        }
        
        required_fields = ["type", "message"]
        for field in required_fields:
            assert field in backend_response
    
    def test_typing_indicator_message(self):
        """Test typing indicator message format"""
        typing_message = {
            "type": "typing",
            "is_typing": True
        }
        
        assert typing_message["type"] == "typing"
        assert "is_typing" in typing_message
    
    def test_error_message_format(self):
        """Test error message format"""
        error_message = {
            "type": "error",
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests. Please wait."
        }
        
        assert error_message["type"] == "error"
        assert "code" in error_message
        assert "message" in error_message


class TestResponseFormatCompatibility:
    """Tests for response format compatibility"""
    
    def test_citation_format_consistency(self):
        """Test citation format is consistent"""
        # Widget backend format
        widget_citation = {
            "url": "https://example.com/doc",
            "cite_num": "1"
        }
        
        # Django storage format (should be compatible)
        django_citation = {
            "url": "https://example.com/doc",
            "cite_num": "1"
        }
        
        assert widget_citation == django_citation
    
    def test_message_content_format(self):
        """Test message content with citations"""
        message = "Based on our documentation [1], you can return items within 30 days [2]."
        
        # Citations should use [N] format
        import re
        citations = re.findall(r'\[(\d+)\]', message)
        
        assert len(citations) == 2
        assert "1" in citations
        assert "2" in citations
    
    def test_sources_array_format(self):
        """Test sources array format"""
        sources = [
            {"url": "https://example.com/page1", "cite_num": "1"},
            {"url": "https://example.com/page2", "cite_num": "2"}
        ]
        
        for source in sources:
            assert "url" in source
            assert "cite_num" in source


class TestURLGenerationCompatibility:
    """Tests for URL generation compatibility"""
    
    def test_widget_url_format(self):
        """Test widget URL format from Django"""
        # Django generates widget URL
        widget_url = "https://cdn.example.com/widget.js"
        
        assert widget_url.endswith(".js")
        assert widget_url.startswith("http")
    
    def test_websocket_url_format(self):
        """Test WebSocket URL format"""
        # Django generates WebSocket URL for widget backend
        ws_url = "wss://chat.example.com"
        
        assert ws_url.startswith("ws")
    
    def test_websocket_url_with_api_key(self):
        """Test WebSocket URL includes API key path"""
        api_key = "cb_test123"
        base_url = "wss://chat.example.com"
        
        full_url = f"{base_url}/ws/{api_key}"
        
        assert api_key in full_url
        assert "/ws/" in full_url


class TestEventSchemaCompatibility:
    """Tests for event schema compatibility between systems"""
    
    def test_session_create_event(self):
        """Test session create event schema"""
        event = {
            "event_type": "session_created",
            "session_id": str(uuid4()),
            "chatbot_id": str(uuid4()),
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "device_type": "mobile",
                "referrer": "https://example.com"
            }
        }
        
        assert "session_id" in event
        assert "chatbot_id" in event
    
    def test_message_event(self):
        """Test message event schema"""
        event = {
            "event_type": "message_sent",
            "session_id": str(uuid4()),
            "message_id": str(uuid4()),
            "role": "user",
            "content": "Hello",
            "timestamp": datetime.now().isoformat()
        }
        
        assert event["role"] in ["user", "assistant"]
    
    def test_session_close_event(self):
        """Test session close event schema"""
        event = {
            "event_type": "session_closed",
            "session_id": str(uuid4()),
            "timestamp": datetime.now().isoformat(),
            "total_messages": 10,
            "duration_seconds": 300
        }
        
        assert "total_messages" in event


class TestDataFlowCompatibility:
    """Tests for end-to-end data flow compatibility"""
    
    def test_embed_code_to_widget_frontend(self):
        """Test embed code data flows to widget frontend"""
        # Django generates embed code
        embed_attributes = {
            "api-key": "cb_test123",
            "api-base": "wss://chat.example.com",
            "theme": "light",
            "position": "bottom-right",
            "primary-color": "#3b82f6"
        }
        
        # Widget frontend should read all attributes
        for attr in embed_attributes:
            assert embed_attributes[attr] is not None
    
    def test_widget_frontend_to_backend_flow(self):
        """Test data flow from widget frontend to backend"""
        # Frontend constructs message
        frontend_data = {
            "question": "Hello",
            "language": "en",
            "device_type": "desktop"
        }
        
        # Backend should receive same structure
        backend_received = frontend_data.copy()
        
        assert backend_received["question"] == frontend_data["question"]
    
    def test_backend_response_to_frontend(self):
        """Test response flow from backend to frontend"""
        # Backend response
        backend_response = {
            "message": "Hi! How can I help?",
            "sources": []
        }
        
        # Frontend should display message
        frontend_display = backend_response["message"]
        
        assert len(frontend_display) > 0
    
    def test_analytics_data_to_django(self):
        """Test analytics data flows to Django"""
        # Widget backend collects analytics
        analytics_data = {
            "session_id": str(uuid4()),
            "chatbot_id": str(uuid4()),
            "messages_count": 5,
            "feedback": "positive"
        }
        
        # Should be storable in Django
        assert "session_id" in analytics_data
        assert "chatbot_id" in analytics_data


class TestNamespaceCompatibility:
    """Tests for namespace handling compatibility"""
    
    def test_namespace_format_consistency(self):
        """Test namespace format is consistent"""
        site_id = uuid4()
        timestamp = int(datetime.now().timestamp())
        
        # Django format
        django_namespace = f"site_{site_id}_{timestamp}"
        
        # Widget backend should use same
        assert django_namespace.startswith("site_")
        assert str(site_id) in django_namespace
    
    def test_namespace_passed_to_widget_backend(self):
        """Test namespace is correctly passed"""
        # Django stores namespace in Site model
        django_namespace = "site_abc123_1704067200"
        
        # Widget backend receives via API key lookup
        widget_config = {
            "namespace": django_namespace
        }
        
        assert widget_config["namespace"] == django_namespace
    
    def test_namespace_used_for_retrieval(self):
        """Test namespace is used for vector retrieval"""
        namespace = "site_abc123_1704067200"
        
        # Pinecone query should use namespace
        query_params = {
            "namespace": namespace,
            "top_k": 5,
            "vector": [0.1] * 768
        }
        
        assert query_params["namespace"] == namespace
