from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from unittest.mock import patch

User = get_user_model()


class ChatAPITestCase(APITestCase):
    """Test chat API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123'
        )
        
        self.org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        
        self.membership = Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain='https://example.com',
            verification_method='dns',
            status='active',
            verified_at='2024-01-01T00:00:00Z'
        )
        
        self.chatbot = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name='Test Chatbot',
            status='active'
        )
        
        self.session = ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            session_key='test-session-001',
            user_id=self.user.id
        )
        
        # Authenticate
        self.client.force_authenticate(user=self.user)
        self.client.defaults['HTTP_X_ORG_ID'] = str(self.org.id)
    
    def test_chat_session_creation(self):
        """Test chat session creation"""
        url = reverse('chat-session-list')
        data = {
            'chatbot_id': str(self.chatbot.id),
            'site_id': str(self.site.id),
            'meta': {'source': 'test'}
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('session_id', response.data)
        self.assertIn('session_key', response.data)
        
        # Check session was created
        session_id = response.data['session_id']
        self.assertTrue(ChatSession.objects.filter(id=session_id).exists())
    
    def test_chat_session_list(self):
        """Test chat session list"""
        url = reverse('chat-session-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    @patch('apps.chat.services.ChatbotService.send_message')
    def test_send_message_success(self, mock_send):
        """Test successful message sending"""
        mock_send.return_value = {
            'assistant_message': 'Hello! How can I help you?',
            'citations': [{'url': 'https://example.com/page1', 'chunk_index': 1, 'score': 0.95}],
            'tokens_in': 10,
            'tokens_out': 25,
            'latency_ms': 1200
        }
        
        url = reverse('send-message', kwargs={'session_id': self.session.id})
        data = {
            'content': 'Hello, can you help me?'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('assistant_message', response.data)
        self.assertIn('citations', response.data)
        self.assertIn('tokens_in', response.data)
        self.assertIn('tokens_out', response.data)
        self.assertIn('latency_ms', response.data)
        
        # Check messages were created
        user_message = ChatMessage.objects.filter(session=self.session, role='user').first()
        assistant_message = ChatMessage.objects.filter(session=self.session, role='assistant').first()
        
        self.assertIsNotNone(user_message)
        self.assertIsNotNone(assistant_message)
        self.assertEqual(user_message.content, 'Hello, can you help me?')
        self.assertEqual(assistant_message.content, 'Hello! How can I help you?')
    
    def test_send_message_validation(self):
        """Test message validation"""
        url = reverse('send-message', kwargs={'session_id': self.session.id})
        data = {
            'content': ''  # Empty content
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content is required', response.data['error'])
    
    def test_session_messages(self):
        """Test getting session messages"""
        # Create some messages
        ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='Hello',
            tokens_in=5
        )
        
        ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Hi there!',
            tokens_out=10
        )
        
        url = reverse('session-messages', kwargs={'session_id': self.session.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
    
    def test_close_session(self):
        """Test closing chat session"""
        url = reverse('close-session', kwargs={'session_id': self.session.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Session closed successfully', response.data['message'])
        
        # Check session was closed
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.closed_at)
    
    def test_organization_access_control(self):
        """Test organization access control"""
        # Create another organization and session
        other_org = Organization.objects.create(
            name='Other Organization',
            slug='other-org'
        )
        
        other_site = Site.objects.create(
            org_id=other_org.id,
            domain='https://other.com',
            verification_method='dns',
            status='active'
        )
        
        other_chatbot = Chatbot.objects.create(
            org_id=other_org.id,
            site_id=other_site.id,
            name='Other Chatbot'
        )
        
        other_session = ChatSession.objects.create(
            org_id=other_org.id,
            chatbot_id=other_chatbot.id,
            site_id=other_site.id,
            session_key='other-session-001'
        )
        
        # Try to access other organization's session
        url = reverse('send-message', kwargs={'session_id': other_session.id})
        data = {'content': 'Hello'}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Session not found', response.data['error'])


class ChatbotServiceTestCase(TestCase):
    """Test chatbot service"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123'
        )
        
        self.org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain='https://example.com',
            verification_method='dns',
            status='active'
        )
        
        self.chatbot = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name='Test Chatbot',
            status='active'
        )
        
        self.session = ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            session_key='test-session-001',
            user_id=self.user.id
        )
    
    @patch('requests.post')
    def test_send_message_success(self, mock_post):
        """Test successful message sending to external service"""
        from apps.chat.services import ChatbotService
        
        # Mock external service response
        mock_response = type('MockResponse', (), {
            'json': lambda: {
                'message': 'Hello! How can I help you?',
                'citations': [{'url': 'https://example.com/page1', 'chunk_index': 1, 'score': 0.95}],
                'tokens_in': 10,
                'tokens_out': 25
            },
            'raise_for_status': lambda: None
        })()
        mock_post.return_value = mock_response
        
        service = ChatbotService()
        result = service.send_message(
            session=self.session,
            user_message='Hello',
            chatbot=self.chatbot
        )
        
        self.assertEqual(result['assistant_message'], 'Hello! How can I help you?')
        self.assertEqual(len(result['citations']), 1)
        self.assertEqual(result['tokens_in'], 10)
        self.assertEqual(result['tokens_out'], 25)
    
    @patch('requests.post')
    def test_send_message_fallback(self, mock_post):
        """Test fallback when external service fails"""
        from apps.chat.services import ChatbotService
        
        # Mock external service failure
        mock_post.side_effect = Exception('Service unavailable')
        
        service = ChatbotService()
        result = service.send_message(
            session=self.session,
            user_message='Hello',
            chatbot=self.chatbot
        )
        
        self.assertIn('trouble connecting', result['assistant_message'])
        self.assertEqual(result['tokens_out'], 20)
    
    def test_create_session(self):
        """Test session creation"""
        from apps.chat.services import ChatbotService
        
        service = ChatbotService()
        session = service.create_session(
            chatbot=self.chatbot,
            site=self.site,
            user_id=self.user.id,
            meta={'source': 'test'}
        )
        
        self.assertIsInstance(session, ChatSession)
        self.assertEqual(session.chatbot_id, self.chatbot.id)
        self.assertEqual(session.site_id, self.site.id)
        self.assertEqual(session.user_id, self.user.id)
    
    def test_close_session(self):
        """Test session closing"""
        from apps.chat.services import ChatbotService
        from django.utils import timezone
        
        service = ChatbotService()
        service.close_session(self.session)
        
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.closed_at)
