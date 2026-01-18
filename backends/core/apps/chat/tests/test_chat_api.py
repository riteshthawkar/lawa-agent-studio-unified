"""
Comprehensive tests for Chat API endpoints.

Tests cover:
- Session creation and management
- Message sending workflow
- Organization access control
- Feedback submission
- Error handling
- Rate limiting considerations
"""

import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from apps.chat.models import ChatSession, ChatMessage, ChatFeedback
from apps.chatbot.models import Chatbot
from apps.sites.models import Site
from apps.organizations.models import Organization, OrganizationMembership

User = get_user_model()


class ChatSessionAPITests(TestCase):
    """Tests for ChatSession API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        # Create user and org
        self.user = User.objects.create_user(
            username='apiuser',
            email='apiuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='API Org',
            owner=self.user
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user,
            organization=self.org,
            defaults={'role': 'owner'}
        )
        self.site = Site.objects.create(
            name='API Site',
            domain='api.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='API Chatbot',
            site=self.site,
            status='active'
        )

        # Create another org for isolation tests
        self.user2 = User.objects.create_user(
            username='apiuser2',
            email='apiuser2@example.com',
            password='TestPassword123!'
        )
        self.org2 = Organization.objects.create(
            name='API Org 2',
            owner=self.user2
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user2,
            organization=self.org2,
            defaults={'role': 'owner'}
        )
        self.site2 = Site.objects.create(
            name='API Site 2',
            domain='api2.example.com',
            org=self.org2
        )
        self.chatbot2 = Chatbot.objects.create(
            name='API Chatbot 2',
            site=self.site2
        )

    def test_create_session_authenticated(self):
        """
        Test creating a chat session with authentication.
        Real-world scenario: Dashboard creates new chat session.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.post('/v1/chat/sessions/', {
            'chatbot_id': str(self.chatbot.id),
            'site_id': str(self.site.id),
            'meta': {'page_url': 'https://api.example.com/pricing'}
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('session_id', response.json())
        self.assertIn('session_key', response.json())

    def test_create_session_unauthenticated(self):
        """
        Test that unauthenticated users cannot create sessions via API.
        Real-world scenario: Security - prevent unauthorized session creation.
        """
        response = self.client.post('/v1/chat/sessions/', {
            'chatbot_id': str(self.chatbot.id),
            'site_id': str(self.site.id)
        }, format='json')

        self.assertIn(response.status_code, [401, 403])

    def test_create_session_missing_chatbot_id(self):
        """
        Test error when chatbot_id is missing.
        Real-world scenario: Invalid API request.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.post('/v1/chat/sessions/', {
            'site_id': str(self.site.id)
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_session_missing_site_id(self):
        """
        Test error when site_id is missing.
        Real-world scenario: Invalid API request.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.post('/v1/chat/sessions/', {
            'chatbot_id': str(self.chatbot.id)
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_session_chatbot_not_owned(self):
        """
        Test error when trying to use another org's chatbot.
        Real-world scenario: Prevent cross-tenant abuse.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.post('/v1/chat/sessions/', {
            'chatbot_id': str(self.chatbot2.id),  # Other org's chatbot
            'site_id': str(self.site2.id)
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_session_chatbot_site_mismatch(self):
        """
        Test error when chatbot doesn't belong to the specified site.
        Real-world scenario: Invalid configuration attempt.
        """
        # Create another site in same org
        another_site = Site.objects.create(
            name='Another Site',
            domain='another.example.com',
            org=self.org
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.post('/v1/chat/sessions/', {
            'chatbot_id': str(self.chatbot.id),
            'site_id': str(another_site.id)  # Mismatched site
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_sessions_filtered_by_organization(self):
        """
        Test that session list only shows user's org sessions.
        Real-world scenario: Dashboard shows only your sessions.
        """
        # Create sessions for both orgs
        session1 = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )
        session2 = ChatSession.objects.create(
            chatbot=self.chatbot2,
            site=self.site2
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get('/v1/chat/sessions/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Should only see own org's sessions
        session_ids = [s['id'] for s in data.get('results', data)]
        self.assertIn(str(session1.id), session_ids)
        self.assertNotIn(str(session2.id), session_ids)

    def test_list_sessions_with_days_filter(self):
        """
        Test filtering sessions by days parameter.
        Real-world scenario: Show recent conversations only.
        """
        # Create session
        ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get('/v1/chat/sessions/?days=7')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_sessions_with_limit(self):
        """
        Test limiting number of sessions returned.
        Real-world scenario: Pagination for performance.
        """
        # Create multiple sessions
        for i in range(10):
            ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site
            )

        self.client.force_authenticate(user=self.user)
        response = self.client.get('/v1/chat/sessions/?limit=5')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertLessEqual(len(results), 5)


class ChatMessageAPITests(TestCase):
    """Tests for Chat Message API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='msgapiuser',
            email='msgapiuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Msg API Org',
            owner=self.user
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user,
            organization=self.org,
            defaults={'role': 'owner'}
        )
        self.site = Site.objects.create(
            name='Msg API Site',
            domain='msgapi.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Msg API Chatbot',
            site=self.site,
            status='active'
        )
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

    @patch('apps.chat.services.ChatbotService.send_message')
    def test_send_message_success(self, mock_send):
        """
        Test successful message sending.
        Real-world scenario: User sends question, gets AI response.
        """
        mock_send.return_value = {
            'assistant_message': 'Here is the answer to your question.',
            'citations': [{'url': 'https://docs.example.com', 'score': 0.9}],
            'tokens_in': 50,
            'tokens_out': 30,
            'latency_ms': 850
        }

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f'/v1/chat/sessions/{self.session.id}/messages/',
            {'content': 'What are your features?'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('assistant_message', data)
        self.assertEqual(data['latency_ms'], 850)

    def test_send_message_unauthenticated(self):
        """
        Test that unauthenticated users cannot send messages via API.
        Real-world scenario: Security check.
        """
        response = self.client.post(
            f'/v1/chat/sessions/{self.session.id}/messages/',
            {'content': 'Hello'},
            format='json'
        )

        self.assertIn(response.status_code, [401, 403])

    def test_send_message_empty_content(self):
        """
        Test error on empty message content.
        Real-world scenario: User submits empty form.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f'/v1/chat/sessions/{self.session.id}/messages/',
            {'content': ''},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_message_other_org_session(self):
        """
        Test cannot send message to another org's session.
        Real-world scenario: Cross-tenant security.
        """
        # Create another org's session
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='TestPassword123!'
        )
        other_org = Organization.objects.create(
            name='Other Org',
            owner=other_user
        )
        OrganizationMembership.objects.get_or_create(
            user=other_user,
            organization=other_org,
            defaults={'role': 'owner'}
        )
        other_site = Site.objects.create(
            name='Other Site',
            domain='other.example.com',
            org=other_org
        )
        other_chatbot = Chatbot.objects.create(
            name='Other Chatbot',
            site=other_site
        )
        other_session = ChatSession.objects.create(
            chatbot=other_chatbot,
            site=other_site
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f'/v1/chat/sessions/{other_session.id}/messages/',
            {'content': 'Trying to access other session'},
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

    def test_get_session_messages(self):
        """
        Test retrieving messages for a session.
        Real-world scenario: Load conversation history.
        """
        # Create some messages
        ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='Hello'
        )
        ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Hi! How can I help you?'
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.get(f'/v1/chat/sessions/{self.session.id}/messages/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        messages = response.json()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['role'], 'user')
        self.assertEqual(messages[1]['role'], 'assistant')


class SessionCloseAPITests(TestCase):
    """Tests for session closing functionality."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='closeuser',
            email='closeuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Close Org',
            owner=self.user
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user,
            organization=self.org,
            defaults={'role': 'owner'}
        )
        self.site = Site.objects.create(
            name='Close Site',
            domain='close.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Close Chatbot',
            site=self.site
        )
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

    def test_close_session_success(self):
        """
        Test successfully closing a session.
        Real-world scenario: User ends chat conversation.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.post(f'/v1/chat/sessions/{self.session.id}/close/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.closed_at)

    def test_close_session_unauthenticated(self):
        """
        Test that unauthenticated users cannot close sessions.
        Real-world scenario: Security check.
        """
        response = self.client.post(f'/v1/chat/sessions/{self.session.id}/close/')

        self.assertIn(response.status_code, [401, 403])


class FeedbackAPITests(TestCase):
    """Tests for feedback submission API."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='fbuser',
            email='fbuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='FB Org',
            owner=self.user
        )
        self.site = Site.objects.create(
            name='FB Site',
            domain='fb.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='FB Chatbot',
            site=self.site
        )
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )
        self.user_message = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='What is pricing?'
        )
        self.assistant_message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Our pricing starts at $29/month.'
        )

    def test_submit_feedback_like(self):
        """
        Test submitting a 'like' feedback.
        Real-world scenario: User clicks thumbs up.
        """
        response = self.client.post(
            f'/v1/chat/messages/{self.assistant_message.id}/feedback/',
            {'feedback_type': 'like'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assistant_message.refresh_from_db()
        self.assertEqual(self.assistant_message.feedback, 'like')

    def test_submit_feedback_dislike(self):
        """
        Test submitting a 'dislike' feedback.
        Real-world scenario: User clicks thumbs down.
        """
        response = self.client.post(
            f'/v1/chat/messages/{self.assistant_message.id}/feedback/',
            {'feedback_type': 'dislike'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assistant_message.refresh_from_db()
        self.assertEqual(self.assistant_message.feedback, 'dislike')

    def test_submit_feedback_on_user_message_rejected(self):
        """
        Test that feedback on user messages is rejected.
        Real-world scenario: Only assistant messages can be rated.
        """
        response = self.client.post(
            f'/v1/chat/messages/{self.user_message.id}/feedback/',
            {'feedback_type': 'like'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_feedback_invalid_type(self):
        """
        Test that invalid feedback types are rejected.
        Real-world scenario: Malformed API request.
        """
        response = self.client.post(
            f'/v1/chat/messages/{self.assistant_message.id}/feedback/',
            {'feedback_type': 'invalid'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_feedback_nonexistent_message(self):
        """
        Test feedback on non-existent message.
        Real-world scenario: Message deleted or invalid ID.
        """
        fake_id = uuid.uuid4()
        response = self.client.post(
            f'/v1/chat/messages/{fake_id}/feedback/',
            {'feedback_type': 'like'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_message_feedback_stats(self):
        """
        Test retrieving feedback statistics for a message.
        Real-world scenario: Display feedback counts in UI.
        """
        # Submit some feedback
        self.client.post(
            f'/v1/chat/messages/{self.assistant_message.id}/feedback/',
            {'feedback_type': 'like'},
            format='json',
            REMOTE_ADDR='192.168.1.1'
        )

        response = self.client.get(
            f'/v1/chat/messages/{self.assistant_message.id}/feedback/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('feedback_counts', data)


class SessionFeedbackStatsAPITests(TestCase):
    """Tests for session-level feedback statistics."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='statsuser',
            email='statsuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Stats Org',
            owner=self.user
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user,
            organization=self.org,
            defaults={'role': 'owner'}
        )
        self.site = Site.objects.create(
            name='Stats Site',
            domain='stats.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Stats Chatbot',
            site=self.site
        )
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        # Create messages with various feedback
        for i in range(5):
            msg = ChatMessage.objects.create(
                session=self.session,
                role='assistant',
                content=f'Response {i}'
            )
            if i < 3:
                msg.feedback = 'like'
            elif i < 4:
                msg.feedback = 'dislike'
            msg.save()

    def test_get_session_feedback_stats(self):
        """
        Test retrieving session feedback statistics.
        Real-world scenario: Dashboard shows session quality metrics.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            f'/v1/chat/sessions/{self.session.id}/feedback-stats/'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['total_messages'], 5)
        self.assertEqual(data['message_feedback']['liked'], 3)
        self.assertEqual(data['message_feedback']['disliked'], 1)

    def test_get_session_feedback_stats_unauthenticated(self):
        """
        Test that unauthenticated users cannot access stats.
        Real-world scenario: Protected business data.
        """
        response = self.client.get(
            f'/v1/chat/sessions/{self.session.id}/feedback-stats/'
        )

        self.assertIn(response.status_code, [401, 403])


class ChatServiceErrorHandlingTests(TestCase):
    """Tests for error handling in chat service."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='erroruser',
            email='erroruser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Error Org',
            owner=self.user
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user,
            organization=self.org,
            defaults={'role': 'owner'}
        )
        self.site = Site.objects.create(
            name='Error Site',
            domain='error.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Error Chatbot',
            site=self.site
        )
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

    @patch('apps.chat.services.ChatbotService.send_message')
    def test_handle_chatbot_service_timeout(self, mock_send):
        """
        Test handling of chatbot service timeout.
        Real-world scenario: External AI service is slow.
        """
        from apps.core.exceptions import ChatbotServiceException
        mock_send.side_effect = ChatbotServiceException(
            'Connection timeout',
            status_code=504
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f'/v1/chat/sessions/{self.session.id}/messages/',
            {'content': 'Hello'},
            format='json'
        )

        # Should return error response, not 500
        self.assertIn(response.status_code, [503, 504])

    @patch('apps.chat.services.ChatbotService.send_message')
    def test_handle_chatbot_service_error(self, mock_send):
        """
        Test handling of chatbot service error.
        Real-world scenario: External AI service returns error.
        """
        from apps.core.exceptions import ChatbotServiceException
        mock_send.side_effect = ChatbotServiceException(
            'Rate limit exceeded',
            status_code=429
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f'/v1/chat/sessions/{self.session.id}/messages/',
            {'content': 'Hello'},
            format='json'
        )

        self.assertIn(response.status_code, [429, 503])


class ChatSecurityTests(TestCase):
    """Security-focused tests for chat functionality."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='secuser',
            email='secuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Sec Org',
            owner=self.user
        )
        OrganizationMembership.objects.get_or_create(
            user=self.user,
            organization=self.org,
            defaults={'role': 'owner'}
        )
        self.site = Site.objects.create(
            name='Sec Site',
            domain='sec.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Sec Chatbot',
            site=self.site
        )

    def test_cannot_access_nonexistent_session(self):
        """
        Test accessing session that doesn't exist.
        Real-world scenario: ID enumeration attack.
        """
        self.client.force_authenticate(user=self.user)
        fake_id = uuid.uuid4()

        response = self.client.get(f'/v1/chat/sessions/{fake_id}/messages/')

        self.assertIn(response.status_code, [403, 404])

    def test_xss_in_message_content(self):
        """
        Test that XSS attempts in message content are stored safely.
        Real-world scenario: Malicious user attempts XSS.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        xss_content = '<script>alert("xss")</script>'
        message = ChatMessage.objects.create(
            session=session,
            role='user',
            content=xss_content
        )

        # Content should be stored as-is (escaping happens on output)
        self.assertEqual(message.content, xss_content)

    def test_sql_injection_in_message_content(self):
        """
        Test that SQL injection attempts are handled safely.
        Real-world scenario: Malicious user attempts SQL injection.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        sql_content = "'; DROP TABLE chat_messages; --"
        message = ChatMessage.objects.create(
            session=session,
            role='user',
            content=sql_content
        )

        # Should be stored safely
        self.assertEqual(message.content, sql_content)

        # Table should still exist
        self.assertTrue(ChatMessage.objects.exists())

    @patch('apps.chat.services.ChatbotService.send_message')
    def test_very_long_message_handling(self, mock_send):
        """
        Test handling of extremely long messages.
        Real-world scenario: User pastes entire document.
        """
        mock_send.return_value = {
            'assistant_message': 'Response to long message',
            'citations': [],
            'tokens_in': 10000,
            'tokens_out': 50,
            'latency_ms': 5000
        }

        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        self.client.force_authenticate(user=self.user)

        # 100KB message
        long_content = 'x' * 100000

        response = self.client.post(
            f'/v1/chat/sessions/{session.id}/messages/',
            {'content': long_content},
            format='json'
        )

        # Should either accept or reject gracefully
        self.assertIn(response.status_code, [200, 400, 413])
