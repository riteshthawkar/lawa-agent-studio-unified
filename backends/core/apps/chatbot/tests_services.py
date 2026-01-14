"""
Comprehensive tests for Chatbot models and services.

These tests cover:
- Chatbot model methods (embed code, URLs, API keys)
- ChatbotService
- ConversationStarter functionality
- QueryCategory functionality
"""
import pytest
from django.test import TestCase
from django.conf import settings
from unittest.mock import patch, MagicMock
from uuid import uuid4

from apps.chatbot.models import Chatbot, ConversationStarter, QueryCategory
from apps.chat.services import ChatbotService
from apps.sites.models import Site
from apps.organizations.models import Organization


class ChatbotModelTests(TestCase):
    """Tests for Chatbot model methods"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id
        )
        self.chatbot = Chatbot.objects.create(
            name="Test Bot",
            site=self.site,
            status='active'
        )
    
    def test_chatbot_generates_api_key_on_save(self):
        """Test that API key is auto-generated on save"""
        chatbot = Chatbot.objects.create(
            name="New Bot",
            site=self.site
        )
        
        self.assertIsNotNone(chatbot.api_key)
        self.assertTrue(chatbot.api_key.startswith('cb_'))
    
    def test_generate_api_key(self):
        """Test API key generation"""
        old_key = self.chatbot.api_key
        self.chatbot.api_key = self.chatbot.generate_api_key()
        self.chatbot.save()
        
        self.assertIsNotNone(self.chatbot.api_key)
        self.assertNotEqual(self.chatbot.api_key, old_key)
    
    def test_generate_embed_code(self):
        """Test embed code generation"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('<script', embed_code)
        self.assertIn(str(self.chatbot.api_key), embed_code)
    
    def test_get_widget_url(self):
        """Test widget URL generation"""
        url = self.chatbot.get_widget_url()
        
        self.assertIsNotNone(url)
        self.assertTrue(url.endswith('.js'))
    
    def test_get_websocket_url(self):
        """Test WebSocket URL generation"""
        url = self.chatbot.get_websocket_url()
        
        self.assertIsNotNone(url)
        # Should contain ws:// or wss://
        self.assertTrue('ws' in url or 'http' in url)
    
    def test_is_active(self):
        """Test is_active property"""
        self.chatbot.status = 'active'
        self.chatbot.save()
        self.chatbot.save()
        self.assertTrue(self.chatbot.is_active)
        
        self.chatbot.status = 'inactive'
        self.chatbot.save()
        self.assertFalse(self.chatbot.is_active)
    
    def test_regenerate_embed_code(self):
        """Test embed code regeneration"""
        old_embed = self.chatbot.embed_code
        self.chatbot.regenerate_embed_code()
        
        self.assertIsNotNone(self.chatbot.embed_code)
        # Embed code should be updated
        self.assertIn('<script', self.chatbot.embed_code)
    
    def test_chatbot_str(self):
        """Test Chatbot string representation"""
        self.assertEqual(str(self.chatbot), f"Chatbot {self.chatbot.name}")


class ConversationStarterTests(TestCase):
    """Tests for ConversationStarter model"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id
        )
        self.chatbot = Chatbot.objects.create(
            name="Test Bot",
            site=self.site
        )
        self.starter = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question="How can I help you today?",
            is_active=True
        )
    
    def test_increment_click(self):
        """Test click count increment"""
        initial_count = self.starter.click_count
        
        self.starter.increment_click()
        
        self.starter.refresh_from_db()
        self.assertEqual(self.starter.click_count, initial_count + 1)
    
    def test_starter_ordering(self):
        """Test conversation starters are ordered correctly"""
        starter2 = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question="Second question",
            display_order=0
        )
        self.starter.display_order = 1
        self.starter.save()
        
        starters = list(ConversationStarter.objects.filter(chatbot=self.chatbot))
        
        self.assertEqual(starters[0].question, "Second question")
    
    def test_starter_str(self):
        """Test ConversationStarter string representation"""
        self.assertIn("How can I", str(self.starter))


class QueryCategoryTests(TestCase):
    """Tests for QueryCategory model"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id
        )
        self.chatbot = Chatbot.objects.create(
            name="Test Bot",
            site=self.site
        )
    
    def test_create_query_category(self):
        """Test creating a query category"""
        category = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name="Support",
            description="General support questions"
        )
        
        self.assertIsNotNone(category.id)
        self.assertEqual(category.name, "Support")
    
    def test_unique_category_per_chatbot(self):
        """Test that category names are unique per chatbot"""
        QueryCategory.objects.create(
            chatbot=self.chatbot,
            name="Support"
        )
        
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            QueryCategory.objects.create(
                chatbot=self.chatbot,
                name="Support"
            )


class ChatbotServiceTests(TestCase):
    """Tests for ChatbotService"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id,
            active_namespace="site_test_123"
        )
        self.chatbot = Chatbot.objects.create(
            name="Test Bot",
            site=self.site
        )
        self.service = ChatbotService()
    
    def test_create_session(self):
        """Test creating a chat session"""
        from apps.chat.models import ChatSession
        
        session = self.service.create_session(
            self.chatbot,
            self.site,
            user_id=None
        )
        
        self.assertIsNotNone(session.id)
        self.assertEqual(session.chatbot_id, self.chatbot.id)
    
    def test_add_message(self):
        """Test adding a message to session"""
        from apps.chat.models import ChatSession
        
        session = self.service.create_session(
            self.chatbot,
            self.site
        )
        
        message = self.service.add_message(
            session,
            role='user',
            content='Hello!',
            tokens_in=5
        )
        
        self.assertIsNotNone(message.id)
        self.assertEqual(message.role, 'user')
        self.assertEqual(message.content, 'Hello!')
    
    def test_close_session(self):
        """Test closing a chat session"""
        from apps.chat.models import ChatSession
        
        session = self.service.create_session(
            self.chatbot,
            self.site
        )
        
        self.service.close_session(session)
        
        session.refresh_from_db()
        self.assertIsNotNone(session.closed_at)
    
    @patch('requests.post')
    def test_send_message_success(self, mock_post):
        """Test successful message sending"""
        from apps.chat.models import ChatSession
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'message': 'Hello! How can I help?',
            'citations': [],
            'tokens_in': 10,
            'tokens_out': 20
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        session = self.service.create_session(
            self.chatbot,
            self.site
        )
        
        result = self.service.send_message(
            session,
            "Hello!",
            self.chatbot
        )
        
        self.assertIn('assistant_message', result)
        self.assertEqual(result['assistant_message'], 'Hello! How can I help?')
    
    @patch('requests.post')
    def test_send_message_timeout(self, mock_post):
        """Test message sending timeout"""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()
        
        from apps.chat.models import ChatSession
        from apps.core.exceptions import ChatbotServiceException
        
        session = self.service.create_session(
            self.chatbot,
            self.site
        )
        
        with self.assertRaises(ChatbotServiceException):
            self.service.send_message(
                session,
                "Hello!",
                self.chatbot
            )
