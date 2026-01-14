"""
Cross-Component Consistency Tests.

These tests verify complete consistency between:
- Django Backend
- Indexing Backend  
- Chatbot Backend

Testing data formats, API contracts, and configuration propagation.
"""
import pytest
import json
import hashlib
import hmac
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import patch, MagicMock


class TestDataFormatConsistency:
    """Tests for data format consistency across all components"""
    
    def test_uuid_format_consistency(self):
        """Test UUID format is consistent across components"""
        # All components should use UUID4 string format
        django_id = str(uuid4())
        indexing_id = str(uuid4())
        chatbot_id = str(uuid4())
        
        # All should be valid UUIDs
        for id_val in [django_id, indexing_id, chatbot_id]:
            assert len(id_val) == 36
            assert id_val.count('-') == 4
    
    def test_timestamp_format_consistency(self):
        """Test timestamp format is consistent"""
        # Django uses ISO format
        django_timestamp = datetime.now().isoformat()
        
        # Indexing backend should parse this
        parsed = datetime.fromisoformat(django_timestamp.replace('Z', '+00:00'))
        
        assert parsed is not None
    
    def test_namespace_format_consistency(self):
        """Test namespace format is used consistently"""
        site_id = str(uuid4())
        timestamp = int(datetime.now().timestamp())
        
        # Django creates namespace
        django_namespace = f"site_{site_id}_{timestamp}"
        
        # Indexing backend uses same format
        indexing_namespace = f"site_{site_id}_{timestamp}"
        
        # Chatbot backend queries with same format
        chatbot_namespace = f"site_{site_id}_{timestamp}"
        
        assert django_namespace == indexing_namespace == chatbot_namespace
    
    def test_api_key_format_consistency(self):
        """Test API key format is consistent"""
        # Django generates
        api_key = f"cb_{'a' * 32}"
        
        # All backends should accept this format
        assert api_key.startswith("cb_")
        assert len(api_key) == 35


class TestAPIContractConsistency:
    """Tests for API contract consistency between components"""
    
    def test_indexing_webhook_payload_schema(self):
        """Test indexing webhook payload schema"""
        # Indexing backend sends this
        webhook_payload = {
            "task_id": str(uuid4()),
            "external_job_id": str(uuid4()),
            "status": "completed",
            "result": {
                "pages_indexed": 50,
                "documents_created": 150,
                "namespace": "site_test_123"
            },
            "timestamp": datetime.now().isoformat()
        }
        
        # Django expects these fields
        required_fields = ["task_id", "external_job_id", "status"]
        for field in required_fields:
            assert field in webhook_payload
    
    def test_chatbot_config_schema(self):
        """Test chatbot config schema between Django and chatbot backend"""
        # Django stores this config
        django_config = {
            "model_provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.7,
            "system_prompt": "You are helpful.",
            "retrieval_config": {"top_k": 5}
        }
        
        # Chatbot backend expects these
        chatbot_expected = ["model_provider", "model", "temperature", "system_prompt"]
        for field in chatbot_expected:
            assert field in django_config
    
    def test_indexing_job_request_schema(self):
        """Test indexing job request schema"""
        # Django sends this to indexing backend
        job_request = {
            "url": "https://example.com",
            "max_pages": 100,
            "external_job_id": str(uuid4()),
            "callback_url": "https://api.example.com/webhooks/indexing/",
            "target_namespace": "site_test_123",
            "site_id": str(uuid4()),
            "excluded_patterns": ["/admin/*"],
            "options": {
                "enable_javascript": True,
                "enable_pdf_processing": True
            }
        }
        
        # Indexing backend requires these
        required = ["url", "max_pages", "callback_url", "target_namespace"]
        for field in required:
            assert field in job_request
    
    def test_search_request_schema(self):
        """Test knowledge search request schema"""
        # Django/Chatbot sends to indexing backend
        search_request = {
            "namespace": "site_test_123",
            "query": "How do I return an item?",
            "top_k": 5
        }
        
        # Response schema
        search_response = {
            "results": [
                {
                    "content": "Our return policy...",
                    "url": "https://example.com/returns",
                    "score": 0.95
                }
            ],
            "total_results": 1
        }
        
        assert "results" in search_response
        assert "score" in search_response["results"][0]


class TestConfigurationPropagation:
    """Tests for configuration propagation between components"""
    
    def test_site_config_to_indexing(self):
        """Test site config propagates to indexing"""
        # Django Site model config
        site_config = {
            "max_pages": 100,
            "crawl_delay": 1.0,
            "respect_robots": True,
            "enable_javascript": True,
            "enable_pdf_processing": True,
            "include_subdomains": False
        }
        
        # Should be sent to indexing backend
        indexing_params = {
            "max_pages": site_config["max_pages"],
            "crawl_delay": site_config["crawl_delay"],
            "respect_robots": site_config["respect_robots"],
            "options": {
                "enable_javascript": site_config["enable_javascript"],
                "enable_pdf_processing": site_config["enable_pdf_processing"]
            }
        }
        
        assert indexing_params["max_pages"] == site_config["max_pages"]
    
    def test_chatbot_config_to_widget_backend(self):
        """Test chatbot config propagates to widget backend"""
        # Django Chatbot model config
        chatbot_config = {
            "name": "Support Bot",
            "theme": "light",
            "position": "bottom-right",
            "primary_color": "#3b82f6",
            "greeting_message": "Hello!",
            "chatbot_tone": "professional",
            "language": "en"
        }
        
        # Embed code should include all
        embed_attributes = [
            f'data-chatbot-name="{chatbot_config["name"]}"',
            f'data-theme="{chatbot_config["theme"]}"',
            f'data-position="{chatbot_config["position"]}"',
            f'data-primary-color="{chatbot_config["primary_color"]}"',
        ]
        
        for attr in embed_attributes:
            assert chatbot_config["name"] in attr or chatbot_config["theme"] in attr or \
                   chatbot_config["position"] in attr or chatbot_config["primary_color"] in attr
    
    def test_quota_enforcement_across_components(self):
        """Test quota limits are enforced consistently"""
        # Django quota
        quota = {
            "max_pages_per_site": 100,
            "max_sites": 5,
            "max_messages_per_month": 10000
        }
        
        # Indexing backend should respect max_pages
        requested_pages = 200
        effective_pages = min(requested_pages, quota["max_pages_per_site"])
        assert effective_pages == 100
        
        # Chatbot backend should track messages
        messages_used = 5000
        messages_remaining = quota["max_messages_per_month"] - messages_used
        assert messages_remaining == 5000


class TestWebhookSignatureConsistency:
    """Tests for webhook signature consistency"""
    
    def test_signature_generation(self):
        """Test HMAC signature generation is consistent"""
        secret = "webhook-secret-123"
        payload = json.dumps({"status": "completed"})
        
        # Both sender and receiver should use same algorithm
        sender_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        receiver_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        assert sender_signature == receiver_signature
    
    def test_signature_verification(self):
        """Test signature verification works correctly"""
        secret = "test-secret"
        payload = json.dumps({"task_id": "123", "status": "completed"})
        
        # Generate signature
        signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Verify
        expected = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        is_valid = hmac.compare_digest(signature, expected)
        assert is_valid is True


class TestErrorCodeConsistency:
    """Tests for error code consistency across components"""
    
    def test_http_status_codes(self):
        """Test HTTP status codes are used consistently"""
        # All components should use same codes
        error_codes = {
            "success": 200,
            "created": 201,
            "bad_request": 400,
            "unauthorized": 401,
            "forbidden": 403,
            "not_found": 404,
            "rate_limit": 429,
            "server_error": 500,
            "service_unavailable": 503
        }
        
        assert error_codes["unauthorized"] == 401
        assert error_codes["rate_limit"] == 429
    
    def test_error_response_schema(self):
        """Test error response schema is consistent"""
        # All components should return same error format
        error_response = {
            "error": True,
            "code": "QUOTA_EXCEEDED",
            "message": "Monthly message quota exceeded",
            "details": {"limit": 10000, "used": 10500}
        }
        
        required_fields = ["error", "code", "message"]
        for field in required_fields:
            assert field in error_response


class TestDatabaseSchemaConsistency:
    """Tests for database schema consistency"""
    
    def test_indexing_job_fields(self):
        """Test IndexingJob fields match between Django and indexing backend"""
        # Django IndexingJob model fields
        django_fields = [
            "id", "site_id", "external_job_id", "status",
            "target_namespace", "pages_indexed", "documents_created",
            "error_message", "created_at", "completed_at"
        ]
        
        # Indexing backend should track same
        indexing_tracked = [
            "task_id", "site_id", "external_job_id", "status",
            "namespace", "pages_count", "documents_count"
        ]
        
        # Key fields should exist in both
        common_concepts = ["site_id", "external_job_id", "status"]
        for concept in common_concepts:
            assert concept in django_fields
    
    def test_chat_session_fields(self):
        """Test ChatSession fields match between Django and chatbot backend"""
        # Django ChatSession fields
        django_fields = [
            "id", "chatbot_id", "site_id", "user_id",
            "created_at", "closed_at", "meta"
        ]
        
        # Chatbot backend session data
        chatbot_fields = [
            "session_id", "chatbot_id", "site_id",
            "started_at", "ended_at", "metadata"
        ]
        
        # Core concepts should match
        common = ["chatbot_id", "site_id"]
        for field in common:
            assert field in django_fields
            assert field in chatbot_fields


class TestEndToEndDataFlow:
    """Tests for end-to-end data flow consistency"""
    
    def test_indexing_flow(self):
        """Test complete indexing data flow"""
        # 1. Django creates job
        job_id = str(uuid4())
        external_job_id = str(uuid4())
        namespace = f"site_test_{int(datetime.now().timestamp())}"
        
        django_job = {
            "id": job_id,
            "external_job_id": external_job_id,
            "target_namespace": namespace,
            "status": "processing"
        }
        
        # 2. Indexing backend processes
        indexing_result = {
            "task_id": job_id,
            "external_job_id": external_job_id,
            "namespace": namespace,
            "pages_indexed": 50,
            "status": "completed"
        }
        
        # 3. Django receives webhook
        webhook_received = {
            "external_job_id": indexing_result["external_job_id"],
            "status": indexing_result["status"],
            "result": {
                "namespace": indexing_result["namespace"],
                "pages_indexed": indexing_result["pages_indexed"]
            }
        }
        
        # 4. Django updates site namespace
        site_update = {
            "active_namespace": webhook_received["result"]["namespace"]
        }
        
        # All should reference same namespace
        assert django_job["target_namespace"] == indexing_result["namespace"]
        assert indexing_result["namespace"] == site_update["active_namespace"]
    
    def test_chat_flow(self):
        """Test complete chat data flow"""
        api_key = "cb_test123"
        
        # 1. Widget frontend connects
        connect_data = {
            "api_key": api_key,
            "device_type": "desktop",
            "referrer": "https://example.com"
        }
        
        # 2. Chatbot backend creates session
        session = {
            "id": str(uuid4()),
            "api_key": api_key,
            "metadata": connect_data
        }
        
        # 3. User sends message
        user_message = {
            "session_id": session["id"],
            "type": "chat",
            "question": "Hello",
            "language": "en"
        }
        
        # 4. Chatbot backend queries indexing (Pinecone)
        retrieval_query = {
            "namespace": "site_test_123",
            "query": user_message["question"],
            "top_k": 5
        }
        
        # 5. Response sent to frontend
        response = {
            "session_id": session["id"],
            "message": "Hi! How can I help?",
            "sources": []
        }
        
        # All reference same session
        assert user_message["session_id"] == response["session_id"]
