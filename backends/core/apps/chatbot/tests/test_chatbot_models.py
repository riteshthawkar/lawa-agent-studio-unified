"""
Comprehensive tests for Chatbot models.

Tests cover:
- Chatbot lifecycle and configuration
- API key generation and uniqueness
- Embed code generation
- Widget configuration
- Query categories and conversation starters
- URL generation methods
"""

import uuid
from django.test import TestCase, override_settings
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from apps.chatbot.models import Chatbot, QueryCategory, ConversationStarter
from apps.sites.models import Site
from apps.organizations.models import Organization

User = get_user_model()


class ChatbotModelTests(TestCase):
    """Tests for Chatbot model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='botuser',
            email='botuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Bot Org',
            owner=self.user
        )
        self.site = Site.objects.create(
            name='Bot Site',
            domain='bot.example.com',
            org=self.org
        )

    def test_chatbot_creation_with_required_fields(self):
        """
        Test creating a chatbot with minimal required fields.
        Real-world scenario: User creates first chatbot.
        """
        chatbot = Chatbot.objects.create(
            name='My First Chatbot',
            site=self.site
        )

        self.assertIsNotNone(chatbot.id)
        self.assertEqual(chatbot.name, 'My First Chatbot')
        self.assertEqual(chatbot.site, self.site)
        self.assertEqual(chatbot.status, 'draft')

    def test_api_key_auto_generated(self):
        """
        Test that API key is automatically generated.
        Real-world scenario: Chatbot needs secure API key for widget.
        """
        chatbot = Chatbot.objects.create(
            name='API Key Test',
            site=self.site
        )

        self.assertIsNotNone(chatbot.api_key)
        self.assertTrue(chatbot.api_key.startswith('cb_'))
        self.assertTrue(len(chatbot.api_key) > 30)

    def test_api_key_is_unique(self):
        """
        Test that API keys are unique across chatbots.
        Real-world scenario: Each widget has unique identifier.
        """
        chatbot1 = Chatbot.objects.create(
            name='Chatbot 1',
            site=self.site
        )
        chatbot2 = Chatbot.objects.create(
            name='Chatbot 2',
            site=self.site
        )

        self.assertNotEqual(chatbot1.api_key, chatbot2.api_key)

    def test_embed_code_auto_generated(self):
        """
        Test that embed code is automatically generated on save.
        Real-world scenario: User copies embed code to website.
        """
        chatbot = Chatbot.objects.create(
            name='Embed Test',
            site=self.site
        )

        self.assertIsNotNone(chatbot.embed_code)
        self.assertIn('<script', chatbot.embed_code)
        self.assertIn(chatbot.api_key, chatbot.embed_code)

    def test_embed_code_contains_configuration(self):
        """
        Test that embed code includes all widget configuration.
        Real-world scenario: Widget needs all settings from embed code.
        """
        chatbot = Chatbot.objects.create(
            name='Config Test',
            site=self.site,
            theme='dark',
            position='bottom-left',
            primary_color='#ff5500',
            greeting_message='Welcome!',
            chatbot_tone='professional'
        )

        embed = chatbot.embed_code
        self.assertIn('data-theme="dark"', embed)
        self.assertIn('data-position="bottom-left"', embed)
        self.assertIn('data-primary-color="#ff5500"', embed)
        self.assertIn('data-greeting="Welcome!"', embed)
        self.assertIn('data-chatbot-tone="professional"', embed)

    def test_chatbot_status_choices(self):
        """
        Test valid chatbot status choices.
        Real-world scenario: Chatbot lifecycle management.
        """
        valid_statuses = ['draft', 'active', 'inactive']

        for status in valid_statuses:
            chatbot = Chatbot.objects.create(
                name=f'Status {status}',
                site=self.site,
                status=status
            )
            self.assertEqual(chatbot.status, status)

    def test_chatbot_tone_choices(self):
        """
        Test valid chatbot tone choices.
        Real-world scenario: User selects conversation style.
        """
        valid_tones = ['professional', 'friendly', 'casual', 'formal']

        for tone in valid_tones:
            chatbot = Chatbot.objects.create(
                name=f'Tone {tone}',
                site=self.site,
                chatbot_tone=tone
            )
            self.assertEqual(chatbot.chatbot_tone, tone)

    def test_chatbot_response_length_choices(self):
        """
        Test valid response length choices.
        Real-world scenario: User prefers detailed or concise answers.
        """
        valid_lengths = ['concise', 'balanced', 'detailed']

        for length in valid_lengths:
            chatbot = Chatbot.objects.create(
                name=f'Length {length}',
                site=self.site,
                response_length=length
            )
            self.assertEqual(chatbot.response_length, length)

    def test_chatbot_theme_choices(self):
        """
        Test valid widget theme choices.
        Real-world scenario: Match website dark/light mode.
        """
        valid_themes = ['light', 'dark', 'auto']

        for theme in valid_themes:
            chatbot = Chatbot.objects.create(
                name=f'Theme {theme}',
                site=self.site,
                theme=theme
            )
            self.assertEqual(chatbot.theme, theme)

    def test_chatbot_position_choices(self):
        """
        Test valid widget position choices.
        Real-world scenario: User places widget on preferred corner.
        """
        valid_positions = ['bottom-right', 'bottom-left']

        for position in valid_positions:
            chatbot = Chatbot.objects.create(
                name=f'Position {position}',
                site=self.site,
                position=position
            )
            self.assertEqual(chatbot.position, position)

    def test_chatbot_color_validation(self):
        """
        Test color fields accept hex colors.
        Real-world scenario: User customizes brand colors.
        """
        chatbot = Chatbot.objects.create(
            name='Color Test',
            site=self.site,
            primary_color='#2563eb',
            text_color='#ffffff'
        )

        self.assertEqual(chatbot.primary_color, '#2563eb')
        self.assertEqual(chatbot.text_color, '#ffffff')

    def test_chatbot_config_json_field(self):
        """
        Test AI configuration JSON field.
        Real-world scenario: Advanced AI settings.
        """
        config = {
            'model_provider': 'openai',
            'model': 'gpt-4',
            'temperature': 0.7,
            'system_prompt': 'You are a helpful assistant.'
        }

        chatbot = Chatbot.objects.create(
            name='Config Test',
            site=self.site,
            config=config
        )

        chatbot.refresh_from_db()
        self.assertEqual(chatbot.config['model'], 'gpt-4')
        self.assertEqual(chatbot.config['temperature'], 0.7)

    def test_chatbot_is_active_property(self):
        """
        Test is_active property.
        Real-world scenario: Check if chatbot should respond.
        """
        active_chatbot = Chatbot.objects.create(
            name='Active Bot',
            site=self.site,
            status='active'
        )
        self.assertTrue(active_chatbot.is_active)

        draft_chatbot = Chatbot.objects.create(
            name='Draft Bot',
            site=self.site,
            status='draft'
        )
        self.assertFalse(draft_chatbot.is_active)

    def test_chatbot_auto_open_default(self):
        """
        Test default value for auto_open.
        Real-world scenario: Widget behavior on page load.
        """
        chatbot = Chatbot.objects.create(
            name='Auto Open Test',
            site=self.site
        )

        self.assertFalse(chatbot.auto_open)

    def test_chatbot_auto_open_in_embed_code(self):
        """
        Test auto_open appears in embed code when enabled.
        Real-world scenario: Widget opens automatically.
        """
        chatbot = Chatbot.objects.create(
            name='Auto Open Enabled',
            site=self.site,
            auto_open=True
        )

        self.assertIn('data-auto-open="true"', chatbot.embed_code)

    def test_chatbot_language_configuration(self):
        """
        Test language configuration.
        Real-world scenario: Chatbot responds in specific language.
        """
        chatbot = Chatbot.objects.create(
            name='Spanish Bot',
            site=self.site,
            language='es'
        )

        self.assertEqual(chatbot.language, 'es')
        self.assertIn('data-language="es"', chatbot.embed_code)

    def test_regenerate_embed_code(self):
        """
        Test regenerating embed code after configuration change.
        Real-world scenario: User updates settings and needs new embed.
        """
        chatbot = Chatbot.objects.create(
            name='Regenerate Test',
            site=self.site,
            theme='light'
        )

        old_embed = chatbot.embed_code

        chatbot.theme = 'dark'
        chatbot.save()
        chatbot.regenerate_embed_code()

        self.assertNotEqual(chatbot.embed_code, old_embed)
        self.assertIn('data-theme="dark"', chatbot.embed_code)

    @override_settings(
        CHATBOT_BACKEND_HOST='api.example.com',
        CHATBOT_BACKEND_PORT='443'
    )
    def test_get_chatbot_backend_url_production(self):
        """
        Test backend URL generation for production.
        Real-world scenario: Widget connects to production API.
        """
        chatbot = Chatbot.objects.create(
            name='Prod Test',
            site=self.site
        )

        url = chatbot.get_chatbot_backend_url()
        self.assertIn('wss://', url)
        self.assertIn('api.example.com', url)

    @override_settings(
        CHATBOT_BACKEND_HOST='localhost',
        CHATBOT_BACKEND_PORT='8002'
    )
    def test_get_chatbot_backend_url_development(self):
        """
        Test backend URL generation for development.
        Real-world scenario: Local development with HTTP.
        """
        chatbot = Chatbot.objects.create(
            name='Dev Test',
            site=self.site
        )

        url = chatbot.get_chatbot_backend_url()
        self.assertIn('ws://', url)
        self.assertIn('localhost:8002', url)

    def test_get_websocket_url(self):
        """
        Test WebSocket URL generation.
        Real-world scenario: Widget establishes WebSocket connection.
        """
        chatbot = Chatbot.objects.create(
            name='WS Test',
            site=self.site
        )

        ws_url = chatbot.get_websocket_url()
        self.assertIn(chatbot.api_key, ws_url)
        self.assertIn('/chat/', ws_url)

    def test_chatbot_advanced_config_defaults(self):
        """
        Test advanced configuration defaults.
        Real-world scenario: Widget uses sensible defaults.
        """
        chatbot = Chatbot.objects.create(
            name='Defaults Test',
            site=self.site
        )

        self.assertTrue(chatbot.enable_typing_indicator)
        self.assertFalse(chatbot.enable_sound_notifications)
        self.assertEqual(chatbot.max_retries, 3)
        self.assertEqual(chatbot.reconnect_delay, 2000)

    def test_chatbot_greeting_message(self):
        """
        Test custom greeting message.
        Real-world scenario: Personalized welcome message.
        """
        chatbot = Chatbot.objects.create(
            name='Greeting Test',
            site=self.site,
            greeting_message='Hi there! How can I assist you today?'
        )

        self.assertEqual(
            chatbot.greeting_message,
            'Hi there! How can I assist you today?'
        )

    def test_chatbot_placeholder_text(self):
        """
        Test custom placeholder text.
        Real-world scenario: Guide user input.
        """
        chatbot = Chatbot.objects.create(
            name='Placeholder Test',
            site=self.site,
            placeholder_text='Ask me anything...'
        )

        self.assertEqual(chatbot.placeholder_text, 'Ask me anything...')

    def test_chatbot_deletion_cascades_sessions(self):
        """
        Test that deleting chatbot cascades to sessions.
        Real-world scenario: Clean up when removing chatbot.
        """
        from apps.chat.models import ChatSession

        chatbot = Chatbot.objects.create(
            name='Cascade Test',
            site=self.site
        )

        # Create sessions
        for i in range(3):
            ChatSession.objects.create(
                chatbot=chatbot,
                site=self.site
            )

        session_count = ChatSession.objects.filter(chatbot=chatbot).count()
        self.assertEqual(session_count, 3)

        chatbot.delete()

        # Sessions should be deleted
        remaining = ChatSession.objects.filter(chatbot_id=chatbot.id).count()
        self.assertEqual(remaining, 0)


class QueryCategoryModelTests(TestCase):
    """Tests for QueryCategory model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='catuser',
            email='catuser@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Cat Org',
            owner=self.user
        )
        self.site = Site.objects.create(
            name='Cat Site',
            domain='cat.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Cat Chatbot',
            site=self.site
        )

    def test_create_query_category(self):
        """
        Test creating a query category.
        Real-world scenario: Admin defines query types for analytics.
        """
        category = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Pricing',
            description='Questions about pricing and plans',
            color='#ff5500'
        )

        self.assertEqual(category.name, 'Pricing')
        self.assertEqual(category.chatbot, self.chatbot)

    def test_query_category_unique_per_chatbot(self):
        """
        Test that category names are unique per chatbot.
        Real-world scenario: Prevent duplicate categories.
        """
        QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Support'
        )

        with self.assertRaises(IntegrityError):
            QueryCategory.objects.create(
                chatbot=self.chatbot,
                name='Support'  # Duplicate
            )

    def test_same_category_name_different_chatbots(self):
        """
        Test that same category name can exist for different chatbots.
        Real-world scenario: Each chatbot has own categories.
        """
        chatbot2 = Chatbot.objects.create(
            name='Another Bot',
            site=self.site
        )

        cat1 = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Support'
        )
        cat2 = QueryCategory.objects.create(
            chatbot=chatbot2,
            name='Support'  # Same name, different chatbot
        )

        self.assertEqual(cat1.name, cat2.name)
        self.assertNotEqual(cat1.chatbot, cat2.chatbot)

    def test_query_category_keywords_json(self):
        """
        Test keywords JSON field.
        Real-world scenario: Keywords help AI classify queries.
        """
        category = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Billing',
            keywords=['invoice', 'payment', 'charge', 'subscription', 'cancel']
        )

        category.refresh_from_db()
        self.assertEqual(len(category.keywords), 5)
        self.assertIn('invoice', category.keywords)

    def test_query_category_ordering(self):
        """
        Test category ordering by display_order.
        Real-world scenario: Show categories in preferred order.
        """
        cat1 = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='First',
            display_order=1
        )
        cat2 = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Second',
            display_order=2
        )
        cat3 = QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Third',
            display_order=0  # Should appear first
        )

        categories = list(QueryCategory.objects.filter(chatbot=self.chatbot))
        self.assertEqual(categories[0].name, 'Third')
        self.assertEqual(categories[1].name, 'First')
        self.assertEqual(categories[2].name, 'Second')

    def test_query_category_active_filter(self):
        """
        Test filtering by active status.
        Real-world scenario: Only use active categories for classification.
        """
        QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Active Cat',
            is_active=True
        )
        QueryCategory.objects.create(
            chatbot=self.chatbot,
            name='Inactive Cat',
            is_active=False
        )

        active_count = QueryCategory.objects.filter(
            chatbot=self.chatbot,
            is_active=True
        ).count()

        self.assertEqual(active_count, 1)


class ConversationStarterModelTests(TestCase):
    """Tests for ConversationStarter model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='starteruser',
            email='starter@example.com',
            password='TestPassword123!'
        )
        self.org = Organization.objects.create(
            name='Starter Org',
            owner=self.user
        )
        self.site = Site.objects.create(
            name='Starter Site',
            domain='starter.example.com',
            org=self.org
        )
        self.chatbot = Chatbot.objects.create(
            name='Starter Chatbot',
            site=self.site
        )

    def test_create_conversation_starter(self):
        """
        Test creating a conversation starter.
        Real-world scenario: Admin adds suggested questions.
        """
        starter = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='What are your pricing plans?'
        )

        self.assertEqual(starter.question, 'What are your pricing plans?')
        self.assertEqual(starter.click_count, 0)

    def test_conversation_starter_click_tracking(self):
        """
        Test click count incrementing.
        Real-world scenario: Track which starters are most used.
        """
        starter = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='How do I get started?'
        )

        self.assertEqual(starter.click_count, 0)

        starter.increment_click()
        starter.refresh_from_db()
        self.assertEqual(starter.click_count, 1)

        starter.increment_click()
        starter.increment_click()
        starter.refresh_from_db()
        self.assertEqual(starter.click_count, 3)

    def test_conversation_starter_ordering(self):
        """
        Test starter ordering by display_order.
        Real-world scenario: Show most important starters first.
        """
        starter1 = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='Question 1',
            display_order=2
        )
        starter2 = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='Question 2',
            display_order=1
        )
        starter3 = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='Question 3',
            display_order=0
        )

        starters = list(ConversationStarter.objects.filter(chatbot=self.chatbot))
        self.assertEqual(starters[0].question, 'Question 3')
        self.assertEqual(starters[1].question, 'Question 2')
        self.assertEqual(starters[2].question, 'Question 1')

    def test_conversation_starter_with_category(self):
        """
        Test starter with category grouping.
        Real-world scenario: Group starters by topic.
        """
        starter = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='How do I upgrade my plan?',
            category='Billing'
        )

        self.assertEqual(starter.category, 'Billing')

    def test_auto_generated_starter(self):
        """
        Test marking starter as auto-generated.
        Real-world scenario: AI-suggested starters from indexed content.
        """
        starter = ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='What features are included?',
            is_auto_generated=True
        )

        self.assertTrue(starter.is_auto_generated)

    def test_active_filter_for_starters(self):
        """
        Test filtering by active status.
        Real-world scenario: Only show active starters to users.
        """
        ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='Active Question',
            is_active=True
        )
        ConversationStarter.objects.create(
            chatbot=self.chatbot,
            question='Inactive Question',
            is_active=False
        )

        active_starters = ConversationStarter.objects.filter(
            chatbot=self.chatbot,
            is_active=True
        )

        self.assertEqual(active_starters.count(), 1)
        self.assertEqual(active_starters.first().question, 'Active Question')

    def test_multiple_starters_for_chatbot(self):
        """
        Test creating multiple starters for same chatbot.
        Real-world scenario: Offer variety of starting questions.
        """
        questions = [
            'What do you offer?',
            'How much does it cost?',
            'Can I get a demo?',
            'How do I contact support?'
        ]

        for i, q in enumerate(questions):
            ConversationStarter.objects.create(
                chatbot=self.chatbot,
                question=q,
                display_order=i
            )

        starters = ConversationStarter.objects.filter(chatbot=self.chatbot)
        self.assertEqual(starters.count(), 4)


class ChatbotMultiTenantTests(TestCase):
    """Multi-tenant isolation tests for Chatbot."""

    def setUp(self):
        """Set up test data for multiple organizations."""
        # Org 1
        self.user1 = User.objects.create_user(
            username='org1user',
            email='org1@example.com',
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

        # Org 2
        self.user2 = User.objects.create_user(
            username='org2user',
            email='org2@example.com',
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

    def test_chatbots_isolated_by_site(self):
        """
        Test that chatbots belong to specific sites.
        Real-world scenario: Each customer has own chatbots.
        """
        chatbot1 = Chatbot.objects.create(
            name='Org1 Bot',
            site=self.site1
        )
        chatbot2 = Chatbot.objects.create(
            name='Org2 Bot',
            site=self.site2
        )

        org1_bots = Chatbot.objects.filter(site__org=self.org1)
        org2_bots = Chatbot.objects.filter(site__org=self.org2)

        self.assertEqual(org1_bots.count(), 1)
        self.assertEqual(org2_bots.count(), 1)
        self.assertEqual(org1_bots.first(), chatbot1)
        self.assertEqual(org2_bots.first(), chatbot2)

    def test_query_categories_isolated_with_chatbot(self):
        """
        Test that categories belong only to their chatbot.
        Real-world scenario: Categories are chatbot-specific.
        """
        chatbot1 = Chatbot.objects.create(name='Bot1', site=self.site1)
        chatbot2 = Chatbot.objects.create(name='Bot2', site=self.site2)

        QueryCategory.objects.create(chatbot=chatbot1, name='Cat1')
        QueryCategory.objects.create(chatbot=chatbot2, name='Cat2')

        bot1_cats = QueryCategory.objects.filter(chatbot__site__org=self.org1)
        bot2_cats = QueryCategory.objects.filter(chatbot__site__org=self.org2)

        self.assertEqual(bot1_cats.count(), 1)
        self.assertEqual(bot2_cats.count(), 1)
        self.assertEqual(bot1_cats.first().name, 'Cat1')
        self.assertEqual(bot2_cats.first().name, 'Cat2')
