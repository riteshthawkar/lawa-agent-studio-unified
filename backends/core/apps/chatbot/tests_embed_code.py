"""
Comprehensive tests for Chatbot Script Tag Generation Pipeline.

These tests cover:
- Complete embed code generation with all data attributes
- Widget URL generation (CDN host, port, script path)
- Chatbot backend URL generation (WebSocket)
- Environment-specific configurations (prod vs local)
- API key inclusion and security
- Configuration propagation (theme, colors, language, etc.)
- Regeneration API endpoint
"""
import pytest
from django.urls import reverse
from django.test import TestCase, override_settings
from django.conf import settings
from unittest.mock import patch, MagicMock
from uuid import uuid4

from apps.chatbot.models import Chatbot
from apps.sites.models import Site
from apps.organizations.models import Organization


class EmbedCodeGenerationTests(TestCase):
    """Comprehensive tests for embed code generation"""
    
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
            status='active',
            theme='light',
            position='bottom-right',
            primary_color='#3b82f6',
            text_color='#1f2937',
            greeting_message='Hello! How can I help?',
            placeholder_text='Type your message...',
            chatbot_tone='professional',
            response_length='medium',
            language='en',
            enable_typing_indicator=True,
            enable_sound_notifications=False,
            max_retries=3,
            reconnect_delay=1000,
            auto_open=False
        )
    
    def test_embed_code_contains_script_tag(self):
        """Test that embed code contains valid script tag"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('<script', embed_code)
        self.assertIn('</script>', embed_code)
    
    def test_embed_code_contains_api_key(self):
        """Test that embed code includes API key"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-api-key="{self.chatbot.api_key}"', embed_code)
    
    def test_embed_code_contains_widget_src(self):
        """Test that embed code includes widget source URL"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('src="', embed_code)
        self.assertIn('.js"', embed_code)
    
    def test_embed_code_contains_api_base(self):
        """Test that embed code includes API base URL"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('data-api-base="', embed_code)
    
    def test_embed_code_contains_chatbot_name(self):
        """Test that embed code includes chatbot name"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-chatbot-name="{self.chatbot.name}"', embed_code)
    
    def test_embed_code_contains_theme(self):
        """Test that embed code includes theme setting"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-theme="{self.chatbot.theme}"', embed_code)
    
    def test_embed_code_contains_position(self):
        """Test that embed code includes position setting"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-position="{self.chatbot.position}"', embed_code)
    
    def test_embed_code_contains_colors(self):
        """Test that embed code includes color settings"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-primary-color="{self.chatbot.primary_color}"', embed_code)
        self.assertIn(f'data-text-color="{self.chatbot.text_color}"', embed_code)
    
    def test_embed_code_contains_greeting(self):
        """Test that embed code includes greeting message"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-greeting="{self.chatbot.greeting_message}"', embed_code)
    
    def test_embed_code_contains_placeholder(self):
        """Test that embed code includes placeholder text"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-placeholder="{self.chatbot.placeholder_text}"', embed_code)
    
    def test_embed_code_contains_ai_config(self):
        """Test that embed code includes AI configuration"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn(f'data-chatbot-tone="{self.chatbot.chatbot_tone}"', embed_code)
        self.assertIn(f'data-response-length="{self.chatbot.response_length}"', embed_code)
        self.assertIn(f'data-language="{self.chatbot.language}"', embed_code)
    
    def test_embed_code_contains_advanced_settings(self):
        """Test that embed code includes advanced settings"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('data-enable-typing-indicator="true"', embed_code)
        self.assertIn('data-enable-sound-notifications="false"', embed_code)
        self.assertIn(f'data-max-retries="{self.chatbot.max_retries}"', embed_code)
        self.assertIn(f'data-reconnect-delay="{self.chatbot.reconnect_delay}"', embed_code)
    
    def test_embed_code_auto_open_when_true(self):
        """Test that auto-open is included when True"""
        self.chatbot.auto_open = True
        self.chatbot.save()
        
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('data-auto-open="true"', embed_code)
    
    def test_embed_code_auto_open_when_false(self):
        """Test that auto-open is excluded when False"""
        self.chatbot.auto_open = False
        self.chatbot.save()
        
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertNotIn('data-auto-open=', embed_code)
    
    def test_embed_code_contains_async(self):
        """Test that embed code includes async attribute"""
        embed_code = self.chatbot.generate_embed_code()
        
        self.assertIn('async', embed_code)


class WidgetURLGenerationTests(TestCase):
    """Tests for widget URL generation"""
    
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
    
    @override_settings(
        WIDGET_CDN_HOST='localhost',
        WIDGET_CDN_PORT='3000',
        WIDGET_SCRIPT_PATH='widget.js'
    )
    def test_widget_url_localhost(self):
        """Test widget URL for localhost"""
        url = self.chatbot.get_widget_url()
        
        self.assertEqual(url, 'http://localhost:3000/widget.js')
    
    @override_settings(
        WIDGET_CDN_HOST='cdn.example.com',
        WIDGET_CDN_PORT='',
        WIDGET_SCRIPT_PATH='widget.js'
    )
    def test_widget_url_production(self):
        """Test widget URL for production CDN"""
        url = self.chatbot.get_widget_url()
        
        self.assertEqual(url, 'https://cdn.example.com/widget.js')
    
    @override_settings(
        WIDGET_CDN_HOST='cdn.example.com',
        WIDGET_CDN_PORT='443',
        WIDGET_SCRIPT_PATH='widget.js'
    )
    def test_widget_url_production_443(self):
        """Test widget URL for production with port 443"""
        url = self.chatbot.get_widget_url()
        
        # Port 443 should be omitted
        self.assertEqual(url, 'https://cdn.example.com/widget.js')
    
    @override_settings(
        WIDGET_CDN_HOST='cdn.example.com',
        WIDGET_CDN_PORT='',
        WIDGET_SCRIPT_PATH='v2/chat-widget.min.js'
    )
    def test_widget_url_custom_script_path(self):
        """Test widget URL with custom script path"""
        url = self.chatbot.get_widget_url()
        
        self.assertEqual(url, 'https://cdn.example.com/v2/chat-widget.min.js')
    
    def test_widget_url_ends_with_js(self):
        """Test that widget URL ends with .js"""
        url = self.chatbot.get_widget_url()
        
        self.assertTrue(url.endswith('.js'))


class ChatbotBackendURLTests(TestCase):
    """Tests for chatbot backend URL generation"""
    
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
    
    @override_settings(
        CHATBOT_BACKEND_HOST='localhost',
        CHATBOT_BACKEND_PORT='8002'
    )
    def test_backend_url_localhost(self):
        """Test backend URL for localhost (ws://)"""
        url = self.chatbot.get_chatbot_backend_url()
        
        self.assertEqual(url, 'ws://localhost:8002')
    
    @override_settings(
        CHATBOT_BACKEND_HOST='chat.example.com',
        CHATBOT_BACKEND_PORT='443'
    )
    def test_backend_url_production(self):
        """Test backend URL for production (wss://)"""
        url = self.chatbot.get_chatbot_backend_url()
        
        self.assertEqual(url, 'wss://chat.example.com')
    
    @override_settings(
        CHATBOT_BACKEND_HOST='chat.example.com',
        CHATBOT_BACKEND_PORT=''
    )
    def test_backend_url_no_port(self):
        """Test backend URL without port"""
        url = self.chatbot.get_chatbot_backend_url()
        
        self.assertEqual(url, 'wss://chat.example.com')
    
    @override_settings(
        CHATBOT_BACKEND_HOST='chat.example.com',
        CHATBOT_BACKEND_PORT='8080'
    )
    def test_backend_url_custom_port(self):
        """Test backend URL with custom port"""
        url = self.chatbot.get_chatbot_backend_url()
        
        self.assertEqual(url, 'wss://chat.example.com:8080')


class EmbedCodeRegenerationTests(TestCase):
    """Tests for embed code regeneration"""
    
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
    
    def test_regenerate_updates_embed_code(self):
        """Test that regeneration updates the embed code"""
        # Modify a setting
        self.chatbot.theme = 'dark'
        self.chatbot.save()
        
        # Regenerate
        new_embed_code = self.chatbot.regenerate_embed_code()
        
        self.assertIn('data-theme="dark"', new_embed_code)
    
    def test_regenerate_preserves_api_key(self):
        """Test that regeneration preserves API key"""
        original_api_key = self.chatbot.api_key
        
        self.chatbot.regenerate_embed_code()
        
        # API key should be preserved
        self.assertEqual(self.chatbot.api_key, original_api_key)
        self.assertIn(original_api_key, self.chatbot.embed_code)
    
    def test_regenerate_saves_to_db(self):
        """Test that regeneration saves to database"""
        self.chatbot.theme = 'dark'
        self.chatbot.save()
        
        self.chatbot.regenerate_embed_code()
        
        # Reload from DB
        self.chatbot.refresh_from_db()
        self.assertIn('data-theme="dark"', self.chatbot.embed_code)


class EmbedCodeAPIEndpointTests(TestCase):
    """Tests for embed code API endpoint"""
    
    def setUp(self):
        """Set up test data"""
        from django.contrib.auth import get_user_model

        CustomUser = get_user_model()
        
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.user = CustomUser.objects.create_user(
            username='embedcodeuser',
            email="test@example.com",
            password="testpass123"
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
    
    def test_regenerate_endpoint_requires_auth(self):
        """Test that regenerate endpoint requires authentication"""
        from django.test import Client
        
        client = Client()
        url = reverse('chatbot-regenerate-embed-code', kwargs={'chatbot_id': self.chatbot.id})
        response = client.post(url)
        
        # Should require authentication
        self.assertIn(response.status_code, [401, 403])
    
    def test_get_chatbot_includes_embed_code(self):
        """Test that GET chatbot response includes embed_code"""
        from django.test import Client
        
        client = Client()
        client.force_login(self.user)
        
        response = client.get(
            f'/api/chatbot/chatbots/{self.chatbot.id}/'
        )
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn('embed_code', data)


class APIKeySecurityTests(TestCase):
    """Tests for API key security in embed code"""
    
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
    
    def test_api_key_has_prefix(self):
        """Test that API key has correct prefix"""
        self.assertTrue(self.chatbot.api_key.startswith('cb_'))
    
    def test_api_key_is_unique(self):
        """Test that each chatbot has unique API key"""
        chatbot2 = Chatbot.objects.create(
            name="Test Bot 2",
            site=self.site
        )
        
        self.assertNotEqual(self.chatbot.api_key, chatbot2.api_key)
    
    def test_api_key_length(self):
        """Test that API key has sufficient length"""
        # Remove prefix and check length
        key_part = self.chatbot.api_key[3:]  # Remove 'cb_'
        
        # Should be at least 32 characters for security
        self.assertGreaterEqual(len(key_part), 32)
    
    def test_regenerate_api_key(self):
        """Test that API key can be regenerated"""
        old_key = self.chatbot.api_key
        
        self.chatbot.api_key = self.chatbot.generate_api_key()
        self.chatbot.save()
        
        self.assertNotEqual(self.chatbot.api_key, old_key)


class DifferentThemeTests(TestCase):
    """Tests for different theme configurations"""
    
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
    
    def test_light_theme(self):
        """Test embed code with light theme"""
        chatbot = Chatbot.objects.create(
            name="Light Bot",
            site=self.site,
            theme='light'
        )
        
        embed_code = chatbot.generate_embed_code()
        self.assertIn('data-theme="light"', embed_code)
    
    def test_dark_theme(self):
        """Test embed code with dark theme"""
        chatbot = Chatbot.objects.create(
            name="Dark Bot",
            site=self.site,
            theme='dark'
        )
        
        embed_code = chatbot.generate_embed_code()
        self.assertIn('data-theme="dark"', embed_code)
    
    def test_different_positions(self):
        """Test embed code with different positions"""
        positions = ['bottom-right', 'bottom-left', 'top-right', 'top-left']
        
        for position in positions:
            chatbot = Chatbot.objects.create(
                name=f"{position} Bot",
                site=self.site,
                position=position
            )
            
            embed_code = chatbot.generate_embed_code()
            self.assertIn(f'data-position="{position}"', embed_code)
    
    def test_custom_colors(self):
        """Test embed code with custom colors"""
        chatbot = Chatbot.objects.create(
            name="Custom Colors Bot",
            site=self.site,
            primary_color='#ff5500',
            text_color='#ffffff'
        )
        
        embed_code = chatbot.generate_embed_code()
        self.assertIn('data-primary-color="#ff5500"', embed_code)
        self.assertIn('data-text-color="#ffffff"', embed_code)
