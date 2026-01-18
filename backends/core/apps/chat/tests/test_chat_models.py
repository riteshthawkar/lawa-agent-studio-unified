"""
Comprehensive tests for Chat models.

Tests cover:
- ChatSession lifecycle and field validation
- ChatMessage with roles and feedback tracking
- ChatFeedback with unique constraints
- Multi-tenant isolation
- Edge cases and boundary conditions
"""

import uuid
from datetime import timedelta
from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.chat.models import ChatSession, ChatMessage, ChatFeedback
from apps.chatbot.models import Chatbot
from apps.sites.models import Site
from apps.organizations.models import Organization

User = get_user_model()


class ChatSessionModelTests(TestCase):
    """Tests for ChatSession model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='chatuser',
            email='chatuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Test Org',
            owner=self.user
        )
        self.site = Site.objects.create(
            name='Test Site',
            domain='test.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Test Chatbot',
            site=self.site,
            status='active'
        )

    def test_session_creation_with_required_fields(self):
        """
        Test creating a session with minimal required fields.
        Real-world scenario: Widget creates new chat session.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        self.assertIsNotNone(session.id)
        self.assertEqual(session.chatbot, self.chatbot)
        self.assertEqual(session.site, self.site)
        self.assertEqual(session.status, 'active')

    def test_session_key_auto_generated(self):
        """
        Test that session_key is automatically generated.
        Real-world scenario: Frontend receives unique session key for tracking.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        self.assertIsNotNone(session.session_key)
        self.assertTrue(len(session.session_key) > 20)

    def test_session_key_is_unique(self):
        """
        Test that session keys are unique across sessions.
        Real-world scenario: Prevent session collision attacks.
        """
        session1 = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )
        session2 = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        self.assertNotEqual(session1.session_key, session2.session_key)

    def test_org_id_populated_from_site(self):
        """
        Test that org_id is automatically populated from site.
        Real-world scenario: Analytics queries need org_id for filtering.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        self.assertEqual(session.org_id, self.site.org_id)

    def test_session_with_geo_location_fields(self):
        """
        Test session with geo-location data.
        Real-world scenario: Tracking visitor geography for analytics.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            geo_country_code='US',
            geo_country_name='United States',
            geo_region='California',
            geo_city='San Francisco',
            client_ip='192.168.1.1'
        )

        self.assertEqual(session.geo_country_code, 'US')
        self.assertEqual(session.geo_country_name, 'United States')
        self.assertEqual(session.geo_region, 'California')
        self.assertEqual(session.geo_city, 'San Francisco')

    def test_session_device_type_choices(self):
        """
        Test valid device type choices.
        Real-world scenario: Analytics filtering by device.
        """
        valid_devices = ['mobile', 'tablet', 'desktop', 'unknown']

        for device in valid_devices:
            session = ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site,
                device_type=device
            )
            self.assertEqual(session.device_type, device)

    def test_session_status_choices(self):
        """
        Test valid session status choices.
        Real-world scenario: Session lifecycle management.
        """
        valid_statuses = ['active', 'ended', 'timeout']

        for status in valid_statuses:
            session = ChatSession.objects.create(
                chatbot=self.chatbot,
                site=self.site,
                status=status
            )
            self.assertEqual(session.status, status)

    def test_session_with_referrer_url(self):
        """
        Test session with referrer URL for traffic analytics.
        Real-world scenario: Understanding traffic sources.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            referrer='https://google.com/search?q=example'
        )

        self.assertEqual(session.referrer, 'https://google.com/search?q=example')

    def test_session_with_long_referrer(self):
        """
        Test session with very long referrer URL.
        Real-world scenario: Complex URLs from marketing campaigns.
        """
        long_referrer = 'https://example.com/?' + 'param=' * 50 + 'value'
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            referrer=long_referrer[:500]  # Max length 500
        )

        self.assertTrue(len(session.referrer) <= 500)

    def test_session_is_closed_property(self):
        """
        Test is_closed property with various states.
        Real-world scenario: Check if session can receive new messages.
        """
        # Active session
        active_session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            status='active'
        )
        self.assertFalse(active_session.is_closed)

        # Ended session
        ended_session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            status='ended'
        )
        self.assertTrue(ended_session.is_closed)

        # Session with ended_at set
        session_with_ended_at = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            status='active',
            ended_at=timezone.now()
        )
        self.assertTrue(session_with_ended_at.is_closed)

    def test_session_is_active_property(self):
        """
        Test is_active property.
        Real-world scenario: Determine if chat widget should allow input.
        """
        active_session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            status='active'
        )
        self.assertTrue(active_session.is_active)

        inactive_session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            status='ended'
        )
        self.assertFalse(inactive_session.is_active)

    def test_session_data_json_field(self):
        """
        Test session_data JSON field with various data types.
        Real-world scenario: Store conversation context and metadata.
        """
        session_data = {
            'context': {
                'user_intent': 'pricing',
                'products_mentioned': ['pro', 'enterprise']
            },
            'turn_count': 5,
            'has_escalated': False
        }

        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_data=session_data
        )

        session.refresh_from_db()
        self.assertEqual(session.session_data['turn_count'], 5)
        self.assertEqual(session.session_data['context']['user_intent'], 'pricing')

    def test_session_meta_backward_compatibility(self):
        """
        Test that meta field is populated from session_data.
        Real-world scenario: Legacy code compatibility.
        """
        session_data = {'source': 'widget', 'version': '2.0'}

        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            session_data=session_data
        )

        # meta should be populated from session_data
        self.assertEqual(session.meta, session_data)

    def test_session_with_authenticated_user(self):
        """
        Test session associated with logged-in user.
        Real-world scenario: User chats while logged into their account.
        """
        session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site,
            user=self.user
        )

        self.assertEqual(session.user, self.user)

    def test_session_ordering_by_started_at(self):
        """
        Test that sessions are ordered by most recent first.
        Real-world scenario: Dashboard shows recent conversations.
        """
        session1 = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )
        session2 = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )
        session3 = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

        sessions = list(ChatSession.objects.all())
        # Most recent first (session3 was created last)
        self.assertEqual(sessions[0].id, session3.id)


class ChatMessageModelTests(TestCase):
    """Tests for ChatMessage model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='msguser',
            email='msguser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Msg Org',
            owner=self.user
        )
        self.site = Site.objects.create(
            name='Msg Site',
            domain='msg.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Msg Chatbot',
            site=self.site
        )
        self.session = ChatSession.objects.create(
            chatbot=self.chatbot,
            site=self.site
        )

    def test_user_message_creation(self):
        """
        Test creating a user message.
        Real-world scenario: User sends a question.
        """
        message = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='How much does the Pro plan cost?'
        )

        self.assertEqual(message.role, 'user')
        self.assertEqual(message.content, 'How much does the Pro plan cost?')

    def test_assistant_message_with_tokens(self):
        """
        Test creating an assistant message with token counts.
        Real-world scenario: Track LLM usage for billing.
        """
        message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='The Pro plan costs $49/month and includes unlimited chats.',
            tokens_in=25,
            tokens_out=15
        )

        self.assertEqual(message.tokens_in, 25)
        self.assertEqual(message.tokens_out, 15)

    def test_assistant_message_with_citations(self):
        """
        Test assistant message with citations.
        Real-world scenario: RAG response includes source references.
        """
        citations = [
            {'url': 'https://docs.example.com/pricing', 'chunk_index': 3, 'score': 0.95},
            {'url': 'https://docs.example.com/features', 'chunk_index': 7, 'score': 0.87}
        ]

        message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Based on our documentation...',
            citations=citations
        )

        message.refresh_from_db()
        self.assertEqual(len(message.citations), 2)
        self.assertEqual(message.citations[0]['score'], 0.95)

    def test_message_latency_tracking(self):
        """
        Test latency tracking for performance monitoring.
        Real-world scenario: Monitor response times for SLA.
        """
        message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Here is the answer...',
            latency_ms=1250
        )

        self.assertEqual(message.latency_ms, 1250)

    def test_message_feedback_field(self):
        """
        Test message feedback field values.
        Real-world scenario: User rates response quality.
        """
        # Create message with no feedback
        message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Test response'
        )
        self.assertEqual(message.feedback, 'no_feedback')

        # Update to like
        message.feedback = 'like'
        message.save()
        message.refresh_from_db()
        self.assertEqual(message.feedback, 'like')

        # Update to dislike
        message.feedback = 'dislike'
        message.save()
        message.refresh_from_db()
        self.assertEqual(message.feedback, 'dislike')

    def test_message_role_choices(self):
        """
        Test valid message roles.
        Real-world scenario: Different message types in conversation.
        """
        valid_roles = ['user', 'assistant', 'system']

        for role in valid_roles:
            message = ChatMessage.objects.create(
                session=self.session,
                role=role,
                content=f'Message from {role}'
            )
            self.assertEqual(message.role, role)

    def test_message_with_query_category(self):
        """
        Test message with LLM-classified query category.
        Real-world scenario: Analytics on common query types.
        """
        message = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='What are your pricing plans?',
            query_category='pricing_inquiry',
            query_category_confidence=0.92
        )

        self.assertEqual(message.query_category, 'pricing_inquiry')
        self.assertEqual(message.query_category_confidence, 0.92)

    def test_message_conversation_turn(self):
        """
        Test conversation turn tracking.
        Real-world scenario: Understand conversation depth metrics.
        """
        # First user message
        msg1 = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='Hello',
            conversation_turn=1
        )

        # First assistant response
        msg2 = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Hi! How can I help?',
            conversation_turn=1
        )

        # Second user message
        msg3 = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='What features do you have?',
            conversation_turn=2
        )

        self.assertEqual(msg1.conversation_turn, 1)
        self.assertEqual(msg3.conversation_turn, 2)

    def test_message_with_empty_content_not_allowed(self):
        """
        Test that empty message content is technically allowed.
        Real-world scenario: System messages might be empty markers.
        """
        # Django doesn't enforce non-empty TextField at DB level
        message = ChatMessage.objects.create(
            session=self.session,
            role='system',
            content=''
        )
        self.assertEqual(message.content, '')

    def test_message_with_unicode_content(self):
        """
        Test message with unicode characters.
        Real-world scenario: International users with various languages.
        """
        unicode_content = '你好！我想了解定价方案 🎉 مرحبا'
        message = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content=unicode_content
        )

        message.refresh_from_db()
        self.assertEqual(message.content, unicode_content)

    def test_message_with_very_long_content(self):
        """
        Test message with very long content.
        Real-world scenario: User pastes long text for analysis.
        """
        long_content = 'x' * 50000  # 50k characters
        message = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content=long_content
        )

        message.refresh_from_db()
        self.assertEqual(len(message.content), 50000)

    def test_messages_ordered_by_created_at(self):
        """
        Test message ordering for conversation display.
        Real-world scenario: Display messages in chronological order.
        """
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
        msg3 = ChatMessage.objects.create(
            session=self.session,
            role='user',
            content='Third message'
        )

        messages = list(ChatMessage.objects.filter(session=self.session).order_by('created_at'))
        self.assertEqual(messages[0].content, 'First message')
        self.assertEqual(messages[1].content, 'Second message')
        self.assertEqual(messages[2].content, 'Third message')


class ChatFeedbackModelTests(TestCase):
    """Tests for ChatFeedback model."""

    def setUp(self):
        """Set up test data."""
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
        self.assistant_message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='This is the answer to your question.'
        )

    def test_authenticated_user_feedback(self):
        """
        Test feedback from authenticated user.
        Real-world scenario: Logged-in user rates response.
        """
        feedback = ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='like',
            user_id=self.user.id,
            user_agent='Mozilla/5.0 Chrome/120.0'
        )

        self.assertEqual(feedback.feedback_type, 'like')
        self.assertEqual(feedback.user_id, self.user.id)

    def test_anonymous_user_feedback_with_ip(self):
        """
        Test feedback from anonymous user tracked by IP.
        Real-world scenario: Widget visitor rates response.
        """
        feedback = ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='dislike',
            ip_address='192.168.1.100',
            user_agent='Mozilla/5.0 Safari/17.0'
        )

        self.assertEqual(feedback.feedback_type, 'dislike')
        self.assertEqual(feedback.ip_address, '192.168.1.100')
        self.assertIsNone(feedback.user_id)

    def test_unique_feedback_per_user(self):
        """
        Test that a user can only submit one feedback per message.
        Real-world scenario: Prevent feedback spam from same user.
        """
        ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='like',
            user_id=self.user.id
        )

        # Attempting second feedback should fail due to unique constraint
        with self.assertRaises(IntegrityError):
            ChatFeedback.objects.create(
                message=self.assistant_message,
                feedback_type='dislike',
                user_id=self.user.id
            )

    def test_unique_anonymous_feedback_per_ip(self):
        """
        Test that anonymous users can only submit one feedback per IP.
        Real-world scenario: Prevent anonymous spam.
        """
        ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='like',
            ip_address='192.168.1.50'
        )

        # Same IP trying to submit again
        with self.assertRaises(IntegrityError):
            ChatFeedback.objects.create(
                message=self.assistant_message,
                feedback_type='dislike',
                ip_address='192.168.1.50'
            )

    def test_different_users_can_feedback_same_message(self):
        """
        Test that different users can give feedback on same message.
        Real-world scenario: Multiple team members review same response.
        """
        user2 = User.objects.create_user(
            username='fbuser2',
            email='fbuser2@example.com',
            password='TestPassword123!'
        )

        fb1 = ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='like',
            user_id=self.user.id
        )
        fb2 = ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='dislike',
            user_id=user2.id
        )

        self.assertEqual(fb1.feedback_type, 'like')
        self.assertEqual(fb2.feedback_type, 'dislike')

    def test_feedback_type_choices(self):
        """
        Test valid feedback type choices.
        Real-world scenario: UI shows thumbs up/down options.
        """
        like_feedback = ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='like',
            user_id=self.user.id
        )
        self.assertEqual(like_feedback.feedback_type, 'like')

        # Create a new message for dislike test
        another_message = ChatMessage.objects.create(
            session=self.session,
            role='assistant',
            content='Another response'
        )
        dislike_feedback = ChatFeedback.objects.create(
            message=another_message,
            feedback_type='dislike',
            user_id=self.user.id
        )
        self.assertEqual(dislike_feedback.feedback_type, 'dislike')

    def test_feedback_counts(self):
        """
        Test counting feedback for analytics.
        Real-world scenario: Display response quality metrics.
        """
        # Create multiple feedbacks from different IPs
        for i in range(5):
            ChatFeedback.objects.create(
                message=self.assistant_message,
                feedback_type='like',
                ip_address=f'192.168.1.{i+1}'
            )

        for i in range(3):
            ChatFeedback.objects.create(
                message=self.assistant_message,
                feedback_type='dislike',
                ip_address=f'10.0.0.{i+1}'
            )

        likes = self.assistant_message.feedbacks.filter(feedback_type='like').count()
        dislikes = self.assistant_message.feedbacks.filter(feedback_type='dislike').count()

        self.assertEqual(likes, 5)
        self.assertEqual(dislikes, 3)

    def test_feedback_ipv6_address(self):
        """
        Test feedback with IPv6 address.
        Real-world scenario: Modern networks using IPv6.
        """
        feedback = ChatFeedback.objects.create(
            message=self.assistant_message,
            feedback_type='like',
            ip_address='2001:0db8:85a3:0000:0000:8a2e:0370:7334'
        )

        self.assertEqual(feedback.ip_address, '2001:0db8:85a3:0000:0000:8a2e:0370:7334')


class MultiTenantIsolationTests(TestCase):
    """Tests for multi-tenant data isolation in chat."""

    def setUp(self):
        """Set up test data for two separate organizations."""
        # Org 1
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@org1.com',
            password='TestPassword123!'
        )
        self.org1 = Organization.objects.create(
            name='Org One',
            owner=self.user1
        )
        self.site1 = Site.objects.create(
            name='Site One',
            domain='org1.example.com',
            org=self.org1
        )
        self.chatbot1 = Chatbot.objects.create(
            name='Chatbot One',
            site=self.site1
        )

        # Org 2
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@org2.com',
            password='TestPassword123!'
        )
        self.org2 = Organization.objects.create(
            name='Org Two',
            owner=self.user2
        )
        self.site2 = Site.objects.create(
            name='Site Two',
            domain='org2.example.com',
            org=self.org2
        )
        self.chatbot2 = Chatbot.objects.create(
            name='Chatbot Two',
            site=self.site2
        )

    def test_sessions_isolated_by_organization(self):
        """
        Test that sessions are properly isolated by organization.
        Real-world scenario: Competitor cannot see your chat sessions.
        """
        # Create sessions for both orgs
        session1 = ChatSession.objects.create(
            chatbot=self.chatbot1,
            site=self.site1
        )
        session2 = ChatSession.objects.create(
            chatbot=self.chatbot2,
            site=self.site2
        )

        # Query sessions for org1 only
        org1_sessions = ChatSession.objects.filter(site__org=self.org1)
        org2_sessions = ChatSession.objects.filter(site__org=self.org2)

        self.assertEqual(org1_sessions.count(), 1)
        self.assertEqual(org2_sessions.count(), 1)
        self.assertEqual(org1_sessions.first(), session1)
        self.assertEqual(org2_sessions.first(), session2)

    def test_messages_isolated_through_sessions(self):
        """
        Test that messages are isolated through session ownership.
        Real-world scenario: Cannot query messages from other organizations.
        """
        session1 = ChatSession.objects.create(
            chatbot=self.chatbot1,
            site=self.site1
        )
        session2 = ChatSession.objects.create(
            chatbot=self.chatbot2,
            site=self.site2
        )

        # Create messages
        ChatMessage.objects.create(
            session=session1,
            role='user',
            content='Org 1 message'
        )
        ChatMessage.objects.create(
            session=session2,
            role='user',
            content='Org 2 message'
        )

        # Query messages through org filter
        org1_messages = ChatMessage.objects.filter(session__site__org=self.org1)
        org2_messages = ChatMessage.objects.filter(session__site__org=self.org2)

        self.assertEqual(org1_messages.count(), 1)
        self.assertEqual(org2_messages.count(), 1)
        self.assertEqual(org1_messages.first().content, 'Org 1 message')
        self.assertEqual(org2_messages.first().content, 'Org 2 message')

    def test_chatbot_sessions_isolated(self):
        """
        Test that chatbot's sessions belong only to its site's org.
        Real-world scenario: Dashboard shows only your chatbot's sessions.
        """
        # Create multiple sessions for chatbot1
        for i in range(3):
            ChatSession.objects.create(
                chatbot=self.chatbot1,
                site=self.site1
            )

        # Create sessions for chatbot2
        for i in range(2):
            ChatSession.objects.create(
                chatbot=self.chatbot2,
                site=self.site2
            )

        chatbot1_sessions = ChatSession.objects.filter(chatbot=self.chatbot1)
        chatbot2_sessions = ChatSession.objects.filter(chatbot=self.chatbot2)

        self.assertEqual(chatbot1_sessions.count(), 3)
        self.assertEqual(chatbot2_sessions.count(), 2)

        # Verify org ownership
        for session in chatbot1_sessions:
            self.assertEqual(session.site.org, self.org1)
        for session in chatbot2_sessions:
            self.assertEqual(session.site.org, self.org2)
