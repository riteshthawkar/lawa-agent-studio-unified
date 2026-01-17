import uuid
import secrets
from django.db import models
from django.conf import settings
from apps.core.models import BaseModel


class ChatSession(BaseModel):
    """Chat session model - Updated to match chatbot backend structure"""
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='chat_sessions', null=True, blank=True)
    chatbot = models.ForeignKey('chatbot.Chatbot', on_delete=models.CASCADE, related_name='chat_sessions', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='chat_sessions')
    session_data = models.JSONField(default=dict, help_text="Session metadata and context")
    started_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    last_activity = models.DateTimeField(auto_now=True, null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('ended', 'Ended'),
            ('timeout', 'Timeout'),
        ],
        default='active'
    )

    # Geo-location fields (populated via server-side IP geolocation)
    geo_country_code = models.CharField(
        max_length=2,
        null=True,
        blank=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g., 'US', 'AE')"
    )
    geo_country_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Full country name"
    )
    geo_region = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Region/state name"
    )
    geo_city = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="City name (optional, for analytics)"
    )
    client_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Client IP address (hashed for privacy in production)"
    )

    # Analytics fields (populated from frontend)
    device_type = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=[
            ('mobile', 'Mobile'),
            ('tablet', 'Tablet'),
            ('desktop', 'Desktop'),
            ('unknown', 'Unknown'),
        ],
        help_text="Device type detected from user agent"
    )
    referrer = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Page referrer URL for traffic source analytics"
    )

    # Legacy fields for backward compatibility
    org_id = models.UUIDField(null=True, blank=True)  # Will be populated from site.org_id
    session_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    meta = models.JSONField(default=dict, null=True, blank=True)  # Legacy field
    closed_at = models.DateTimeField(null=True, blank=True)  # Legacy field

    class Meta:
        db_table = 'chat_sessions'
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['chatbot']),
            models.Index(fields=['user']),
            models.Index(fields=['status']),
            models.Index(fields=['started_at']),
            models.Index(fields=['last_activity']),
            # Geo indexes for analytics
            models.Index(fields=['geo_country_code']),
            models.Index(fields=['geo_country_code', 'geo_region']),
            # Analytics indexes
            models.Index(fields=['device_type']),
            # Legacy indexes for backward compatibility
            models.Index(fields=['org_id']),
            models.Index(fields=['session_key']),
        ]
        ordering = ['-started_at']

    def __str__(self):
        return f"Session {self.session_key}"

    def save(self, *args, **kwargs):
        # Populate org_id from site if not set
        if not self.org_id and self.site_id:
            self.org_id = self.site.org_id
        
        # Generate session_key if not set (for backward compatibility)
        if not self.session_key:
            self.session_key = secrets.token_urlsafe(32)
        
        # Update meta from session_data for backward compatibility
        if not self.meta and self.session_data:
            self.meta = self.session_data
            
        super().save(*args, **kwargs)

    @property
    def is_closed(self):
        """Check if session is closed (backward compatibility)"""
        return self.status == 'ended' or self.ended_at is not None or self.closed_at is not None
    
    @property
    def is_active(self):
        """Check if session is active"""
        return self.status == 'active' and not self.is_closed


class ChatMessage(BaseModel):
    """Chat message model"""
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(
        max_length=20,
        choices=[
            ('user', 'User'),
            ('assistant', 'Assistant'),
            ('system', 'System'),
        ]
    )
    content = models.TextField()
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    citations = models.JSONField(default=list)  # List of {url, chunk_index, score}
    latency_ms = models.IntegerField(default=0)
    feedback = models.CharField(
        max_length=15,
        choices=[
            ('like', 'Like'),
            ('dislike', 'Dislike'),
            ('no_feedback', 'No Feedback'),
        ],
        default='no_feedback',
        null=True,
        blank=True
    )

    # Analytics fields
    conversation_turn = models.IntegerField(
        null=True,
        blank=True,
        help_text="Turn number in the conversation (1-indexed)"
    )

    # Query classification (populated by LLM-based classification agent)
    query_category = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        help_text="LLM-classified query category (e.g., 'billing', 'support', 'product_info')"
    )
    query_category_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Confidence score for the category classification (0.0 to 1.0)"
    )

    class Meta:
        db_table = 'chat_messages'
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'
        indexes = [
            models.Index(fields=['session']),
            models.Index(fields=['role']),
            models.Index(fields=['created_at']),
            models.Index(fields=['query_category']),
            models.Index(fields=['query_category', 'created_at']),
            models.Index(fields=['conversation_turn']),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


class ChatFeedback(BaseModel):
    """Detailed feedback model for chat messages"""
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name='feedbacks')
    feedback_type = models.CharField(
        max_length=10,
        choices=[
            ('like', 'Like'),
            ('dislike', 'Dislike'),
        ]
    )
    user_id = models.UUIDField(null=True, blank=True)  # Optional user association
    ip_address = models.GenericIPAddressField(null=True, blank=True)  # For anonymous feedback
    user_agent = models.TextField(null=True, blank=True)  # Browser info
    
    class Meta:
        db_table = 'chat_feedbacks'
        verbose_name = 'Chat Feedback'
        verbose_name_plural = 'Chat Feedbacks'
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['feedback_type']),
            models.Index(fields=['user_id']),
            models.Index(fields=['created_at']),
        ]
        # Ensure one feedback per message per user (if user_id is provided)
        constraints = [
            models.UniqueConstraint(
                fields=['message', 'user_id'],
                condition=models.Q(user_id__isnull=False),
                name='unique_user_feedback_per_message'
            ),
            models.UniqueConstraint(
                fields=['message', 'ip_address'],
                condition=models.Q(user_id__isnull=True, ip_address__isnull=False),
                name='unique_anonymous_feedback_per_message'
            ),
        ]

    def __str__(self):
        user_info = f"User {self.user_id}" if self.user_id else f"IP {self.ip_address}"
        return f"{self.feedback_type} from {user_info} on {self.message}"
