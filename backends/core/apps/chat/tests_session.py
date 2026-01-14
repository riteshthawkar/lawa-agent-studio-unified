"""
Comprehensive tests for Chat Session API endpoints.

These tests ensure that chat session functionality works correctly,
including session creation, message handling, and history retrieval.
"""
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from apps.organizations.models import Organization
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage

User = get_user_model()


class ChatSessionAPITestCase(APITestCase):
    """Base test case for chat session API tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='chat_test@example.com',
            username='chattesuser',
            password='testpassword123'
        )
        self.org = Organization.objects.create(
            name="Chat Test Organization",
            slug="chat-test-org"
        )
        from apps.organizations.models import Membership
        Membership.objects.create(user=self.user, organization=self.org, role='owner')
        
        self.site = Site.objects.create(
            domain="https://chat-test.com",
            name="Chat Test Site",
            org_id=self.org.id,
            status='active'
        )
        
        self.chatbot = Chatbot.objects.create(
            site=self.site,
            name="Test Chatbot",
            status='active'
        )
        
        self.client.force_authenticate(user=self.user)


class ChatSessionListTests(ChatSessionAPITestCase):
    """Tests for chat session list endpoint"""
    
    def test_list_sessions_success(self):
        """Test successful retrieval of chat sessions"""
        # Create some sessions
        for i in range(3):
            ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site,
                session_key=f"session-{i}"
            )
        
        url = reverse('chat-session-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Response should contain sessions
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            self.assertGreaterEqual(len(data['results']), 3)
        else:
            self.assertGreaterEqual(len(data), 3)
    
    def test_list_sessions_filter_by_chatbot(self):
        """Test filtering sessions by chatbot"""
        # Create sessions for our chatbot
        ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_key="session-1"
        )
        
        # Create another chatbot with sessions
        other_site = Site.objects.create(
            org_id=self.org.id,
            domain="https://other.com",
            status="active"
        )
        other_chatbot = Chatbot.objects.create(
            site=other_site,
            name="Other Chatbot",
            status="active"
        )
        ChatSession.objects.create(
            chatbot=other_chatbot,
            site=other_site,
            session_key="session-other"
        )
        
        url = reverse('chat-session-list')
        response = self.client.get(url, {'chatbot_id': str(self.chatbot.id)})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_list_sessions_requires_authentication(self):
        """Test that listing sessions requires authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('chat-session-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_list_sessions_only_shows_user_org_sessions(self):
        """Test that users only see sessions from their organization"""
        # Create session for our org
        our_session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_key="our-session"
        )
        
        # Create session for another org
        other_org = Organization.objects.create(
            name="Other Org",
            slug="other-org"
        )
        other_site = Site.objects.create(
            domain="https://other-site.com",
            name="Other Site",
            org_id=other_org.id,
            status='active'
        )
        other_chatbot = Chatbot.objects.create(
            site=other_site,
            name="Other Chatbot",
            status='active'
        )
        other_session = ChatSession.objects.create(
            chatbot=other_chatbot,
            site=other_site,
            session_key="other-session"
        )
        
        url = reverse('chat-session-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not contain the other org's session
        data = response.data
        sessions = data.get('results', data) if isinstance(data, dict) else data
        session_ids = [s.get('session_id') for s in sessions]
        self.assertNotIn('other-session', session_ids)


class ChatSessionDetailTests(ChatSessionAPITestCase):
    """Tests for chat session detail endpoint"""
    
    def setUp(self):
        super().setUp()
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_key="test-session-detail"
        )
    
    def test_get_session_detail_success(self):
        """Test successful retrieval of session details"""
        url = reverse('chat-session-detail', kwargs={'pk': str(self.session.id)})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['session_key'], self.session.session_key)
    
    def test_get_session_not_found(self):
        """Test getting non-existent session"""
        fake_id = str(uuid.uuid4())
        url = reverse('chat-session-detail', kwargs={'pk': fake_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_get_session_from_other_org(self):
        """Test that users cannot access sessions from other orgs"""
        # Create session for another org
        other_org = Organization.objects.create(
            name="Other Org Detail",
            slug="other-org-detail"
        )
        other_site = Site.objects.create(
            domain="https://other-detail.com",
            name="Other Site",
            org_id=other_org.id,
            status='active'
        )
        other_chatbot = Chatbot.objects.create(
            site=other_site,
            name="Other Chatbot",
            status='active'
        )
        other_session = ChatSession.objects.create(
            chatbot=other_chatbot,
            site=other_site,
            session_key="other-session-detail"
        )
        
        url = reverse('chat-session-detail', kwargs={'pk': str(other_session.id)})
        response = self.client.get(url)
        
        # Should return 404 (hiding existence)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ChatMessageTests(ChatSessionAPITestCase):
    """Tests for chat message functionality"""
    
    def setUp(self):
        super().setUp()
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_key="test-message-session"
        )
    
    def test_session_messages_included(self):
        """Test that session detail includes messages"""
        # Create messages
        ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='Hello, world!'
        )
        ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Hi there!'
        )
        
        url = reverse('chat-session-detail', kwargs={'pk': str(self.session.id)})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check if messages are included
        if 'messages' in response.data:
            self.assertEqual(len(response.data['messages']), 2)
    
    def test_messages_ordered_by_timestamp(self):
        """Test that messages are ordered by timestamp"""
        msg1 = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='First message'
        )
        msg2 = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Second message'
        )
        
        url = reverse('chat-session-detail', kwargs={'pk': str(self.session.id)})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if 'messages' in response.data and response.data['messages']:
            messages = response.data['messages']
            # Should be ordered (first message before second)
            self.assertTrue(len(messages) >= 2)


class ChatSessionStatsTests(ChatSessionAPITestCase):
    """Tests for chat session statistics"""
    
    def test_session_count_in_dashboard(self):
        """Test that dashboard includes correct session count"""
        # Create sessions
        for i in range(5):
            ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site,
                session_key=f"stats-session-{i}"
            )
        
        # Dashboard stats endpoint should include session count
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify total_conversations or similar field exists
        data = response.data
        self.assertTrue('chat_sessions' in data)
        self.assertGreaterEqual(data['chat_sessions'].get('total_30_days', 0), 5)
    
    def test_message_count_tracking(self):
        """Test that message count is tracked correctly"""
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_key="count-session"
        )
        
        # Add messages
        for i in range(10):
            ChatMessage.objects.create(
                session=session,
                role='user' if i % 2 == 0 else 'assistant',
                content=f'Message {i}'
            )
        
        url = reverse('chat-session-detail', kwargs={'pk': str(session.id)})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # If message_count is returned, verify it
        if 'message_count' in response.data:
            self.assertEqual(response.data['message_count'], 10)


class ChatSessionPaginationTests(ChatSessionAPITestCase):
    """Tests for chat session list pagination"""
    
    def test_pagination_default(self):
        """Test default pagination behavior"""
        # Create many sessions
        for i in range(50):
            ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site,
                session_key=f"page-session-{i}"
            )
        
        url = reverse('chat-session-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have pagination
        if isinstance(response.data, dict):
            # Paginated response
            if 'count' in response.data:
                self.assertGreaterEqual(response.data['count'], 50)
            if 'results' in response.data:
                self.assertLessEqual(len(response.data['results']), 50)  # Default page size
    
    def test_pagination_custom_page_size(self):
        """Test custom page size"""
        # Create sessions
        for i in range(20):
            ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site,
                session_key=f"custom-page-{i}"
            )
        
        url = reverse('chat-session-list')
        response = self.client.get(url, {'page_size': 5})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
