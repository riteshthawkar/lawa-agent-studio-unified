import uuid
import secrets
from django.db import models
from apps.core.models import BaseModel


class Chatbot(BaseModel):
    """Simplified Chatbot model for MVP - no organizations, global config"""
    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='chatbots',
        help_text="Associated knowledge base - chatbots are deleted when knowledge base is deleted"
    )
    name = models.CharField(max_length=255, help_text="Chatbot name")
    description = models.TextField(blank=True, help_text="Chatbot description")
    status = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        default='draft',
        help_text="Chatbot deployment status"
    )
    embed_code = models.TextField(blank=True, help_text="Embed code for website")
    api_key = models.CharField(max_length=255, unique=True, help_text="API key for chatbot access")

    # AI Behavior Configuration
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="AI Behavior Config (model, prompt, temperature)"
    )

    # Chatbot Personality Configuration
    chatbot_tone = models.CharField(
        max_length=20,
        choices=[
            ('professional', 'Professional'),
            ('friendly', 'Friendly'),
            ('casual', 'Casual'),
            ('formal', 'Formal'),
        ],
        default='friendly',
        help_text="Chatbot conversation tone"
    )
    response_length = models.CharField(
        max_length=20,
        choices=[
            ('concise', 'Concise'),
            ('balanced', 'Balanced'),
            ('detailed', 'Detailed'),
        ],
        default='balanced',
        help_text="Preferred response length"
    )

    # Widget Configuration Fields
    theme = models.CharField(
        max_length=10,
        choices=[
            ('light', 'Light'),
            ('dark', 'Dark'),
            ('auto', 'Auto'),
        ],
        default='light',
        help_text="Widget theme (light, dark, or auto for system preference)"
    )
    position = models.CharField(
        max_length=15,
        choices=[
            ('bottom-right', 'Bottom Right'),
            ('bottom-left', 'Bottom Left'),
        ],
        default='bottom-right',
        help_text="Widget position on page"
    )
    primary_color = models.CharField(
        max_length=7,
        default='#2563eb',
        help_text="Primary/background color for widget (hex format)"
    )
    text_color = models.CharField(
        max_length=7,
        default='#000000',
        help_text="Text color for widget (hex format)"
    )
    auto_open = models.BooleanField(
        default=False,
        help_text="Auto-open chat on page load"
    )
    greeting_message = models.TextField(
        max_length=500,
        default='Hello! How can I help you today?',
        help_text="Initial greeting message"
    )
    placeholder_text = models.CharField(
        max_length=100,
        default='Type your message...',
        help_text="Input placeholder text"
    )

    # Advanced Configuration
    enable_typing_indicator = models.BooleanField(
        default=True,
        help_text="Show typing indicator"
    )
    enable_sound_notifications = models.BooleanField(
        default=False,
        help_text="Enable sound notifications"
    )
    max_retries = models.PositiveIntegerField(
        default=3,
        help_text="Maximum connection retry attempts"
    )
    reconnect_delay = models.PositiveIntegerField(
        default=2000,
        help_text="Reconnection delay in milliseconds"
    )

    # Language Configuration
    language = models.CharField(
        max_length=10,
        default='en',
        help_text="Response language code (e.g., 'en', 'es', 'fr')"
    )
    
    class Meta:
        db_table = 'chatbots'
        verbose_name = 'Chatbot'
        verbose_name_plural = 'Chatbots'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['status']),
            models.Index(fields=['api_key']),
        ]
    
    def __str__(self):
        return f"Chatbot {self.name}"
    
    def save(self, *args, **kwargs):
        # Generate API key first if not present
        if not self.api_key:
            self.api_key = self.generate_api_key()
        
        # Save first to ensure we have an ID
        super().save(*args, **kwargs)
        
        # Generate embed code after save (when we have ID and API key)
        if not self.embed_code:
            self.embed_code = self.generate_embed_code()
            # Save again to store the embed code
            super().save(update_fields=['embed_code'])
    
    def generate_api_key(self):
        """Generate unique API key for chatbot"""
        return f"cb_{secrets.token_urlsafe(32)}"
    
    def generate_embed_code(self):
        """Generate comprehensive embed code for website integration with all configurations"""
        widget_url = self.get_widget_url()

        # Build list of data attributes
        attributes = [
            f'src="{widget_url}"',
            f'data-api-key="{self.api_key}"',
            f'data-api-base="{self.get_chatbot_backend_url()}"',
            f'data-api-url="{self.get_api_url()}"',
            f'data-chatbot-name="{self.name}"',
            # Appearance
            f'data-theme="{self.theme}"',
            f'data-position="{self.position}"',
            f'data-primary-color="{self.primary_color}"',
            f'data-text-color="{self.text_color}"',
            # Behavior
            f'data-greeting="{self.greeting_message}"',
            f'data-placeholder="{self.placeholder_text}"',
            # AI Configuration
            f'data-chatbot-tone="{self.chatbot_tone}"',
            f'data-response-length="{self.response_length}"',
            f'data-language="{self.language}"',
            # Advanced
            f'data-enable-typing-indicator="{str(self.enable_typing_indicator).lower()}"',
            f'data-enable-sound-notifications="{str(self.enable_sound_notifications).lower()}"',
            f'data-max-retries="{self.max_retries}"',
            f'data-reconnect-delay="{self.reconnect_delay}"',
        ]

        # Add auto-open only if true
        if self.auto_open:
            attributes.append('data-auto-open="true"')

        # Add async attribute
        attributes.append('async')

        # Format embed code with proper indentation
        attr_str = '\n  '.join(attributes)
        embed_code = f'<script\n  {attr_str}>\n</script>'

        return embed_code
    
    def get_api_base_url(self):
        """Get API base URL for embed code (legacy)"""
        from django.conf import settings
        return settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost'
    
    def get_chatbot_backend_url(self):
        """Get chatbot backend URL for WebSocket connections"""
        from django.conf import settings
        chatbot_host = getattr(settings, 'CHATBOT_BACKEND_HOST', 'localhost')
        chatbot_port = getattr(settings, 'CHATBOT_BACKEND_PORT', '8002')
        
        # Determine protocol based on environment
        protocol = 'wss' if chatbot_host != 'localhost' else 'ws'
        
        if chatbot_port and chatbot_port != '80' and chatbot_port != '443':
            return f"{protocol}://{chatbot_host}:{chatbot_port}"
        else:
            return f"{protocol}://{chatbot_host}"

    def get_api_url(self):
        """Get chatbot API URL for HTTP connections (fetch)"""
        from django.conf import settings
        chatbot_host = getattr(settings, 'CHATBOT_BACKEND_HOST', 'localhost')
        chatbot_port = getattr(settings, 'CHATBOT_BACKEND_PORT', '8002')
        
        # Determine protocol based on environment
        protocol = 'https' if chatbot_host != 'localhost' else 'http'
        
        if chatbot_port and chatbot_port != '80' and chatbot_port != '443':
            return f"{protocol}://{chatbot_host}:{chatbot_port}"
        else:
            return f"{protocol}://{chatbot_host}"
    
    def get_widget_url(self):
        """Get widget JavaScript file URL (full path including .js file)"""
        from django.conf import settings
        widget_host = getattr(settings, 'WIDGET_CDN_HOST', 'localhost')
        widget_port = getattr(settings, 'WIDGET_CDN_PORT', '')
        widget_script = getattr(settings, 'WIDGET_SCRIPT_PATH', 'widget.js')
        
        # Determine protocol for widget
        protocol = 'https' if widget_host != 'localhost' else 'http'
        
        # Build base URL
        if widget_port and widget_port not in ('', '80', '443'):
            base_url = f"{protocol}://{widget_host}:{widget_port}"
        else:
            base_url = f"{protocol}://{widget_host}"
        
        # Return full URL with script path
        return f"{base_url}/{widget_script}"
    
    def regenerate_embed_code(self):
        """Regenerate embed code (useful after configuration changes)"""
        self.embed_code = self.generate_embed_code()
        self.save(update_fields=['embed_code'])
        return self.embed_code
    
    def get_websocket_url(self):
        """Get the full WebSocket URL for this chatbot"""
        base_url = self.get_chatbot_backend_url()
        return f"{base_url}/chat/{self.api_key}"
    
    @property
    def is_active(self):
        """Check if chatbot is active"""
        return self.status == 'active'
    
    @property
    def widget_preview_url(self):
        """Get URL for widget preview/testing"""
        widget_base = self.get_widget_url()
        return f"{widget_base}/preview?api_key={self.api_key}"


class QueryCategory(BaseModel):
    """
    User-defined query categories for classifying chat messages.
    These categories are used by the query classification agent to categorize
    incoming user queries for analytics and routing purposes.
    """
    chatbot = models.ForeignKey(
        Chatbot,
        on_delete=models.CASCADE,
        related_name='query_categories',
        help_text="The chatbot this category belongs to"
    )
    name = models.CharField(
        max_length=100,
        help_text="Category name (e.g., 'Billing', 'Technical Support', 'Product Info')"
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text="Description to help the AI classify queries into this category"
    )
    keywords = models.JSONField(
        default=list,
        blank=True,
        help_text="List of keywords/phrases that indicate this category"
    )
    color = models.CharField(
        max_length=7,
        default='#6366f1',
        help_text="Color for displaying this category in analytics (hex format)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this category is currently active for classification"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in UI (lower numbers appear first)"
    )

    class Meta:
        db_table = 'query_categories'
        verbose_name = 'Query Category'
        verbose_name_plural = 'Query Categories'
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['chatbot', 'is_active']),
            models.Index(fields=['display_order']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['chatbot', 'name'],
                name='unique_category_name_per_chatbot'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.chatbot.name})"


class ConversationStarter(BaseModel):
    """
    Suggested conversation starter questions for a chatbot.
    These are displayed to users to help them start a conversation.
    """
    chatbot = models.ForeignKey(
        Chatbot,
        on_delete=models.CASCADE,
        related_name='conversation_starters',
        help_text="The chatbot this starter belongs to"
    )
    question = models.CharField(
        max_length=500,
        help_text="The suggested question text"
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Optional category for grouping starters"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this starter is currently active"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Display order (lower numbers appear first)"
    )
    click_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this starter has been clicked"
    )
    is_auto_generated = models.BooleanField(
        default=False,
        help_text="Whether this was auto-generated from indexed content"
    )

    class Meta:
        db_table = 'conversation_starters'
        verbose_name = 'Conversation Starter'
        verbose_name_plural = 'Conversation Starters'
        ordering = ['display_order', '-created_at']
        indexes = [
            models.Index(fields=['chatbot', 'is_active']),
            models.Index(fields=['display_order']),
        ]

    def __str__(self):
        return f"{self.question[:50]}..."

    def increment_click(self):
        """Increment the click count for this starter"""
        self.click_count += 1
        self.save(update_fields=['click_count'])
