import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.core.models import BaseModel


class User(AbstractUser):
    """Custom User model with additional fields"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('suspended', 'Suspended'),
        ],
        default='active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'name']
    
    # Email verification
    is_email_verified = models.BooleanField(default=False)

    class Meta:
        db_table = 'auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.email


class EmailVerification(models.Model):
    """Model to store OTPs for email verification"""
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'api_email_verification'
        verbose_name = 'Email Verification'
        verbose_name_plural = 'Email Verifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} ({self.otp})"


class APIKey(BaseModel):
    """API Key model for organization-scoped authentication"""
    org_id = models.UUIDField()
    name = models.CharField(max_length=255)
    token_hash = models.CharField(max_length=255, unique=True)
    scopes = models.JSONField(default=list)  # List of permission scopes
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional expiration date for the API key")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'api_keys'
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'
        indexes = [
            models.Index(fields=['org_id']),
            models.Index(fields=['token_hash']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.org_id})"

    def is_expired(self):
        """Check if the API key has expired"""
        if not self.expires_at:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at

    def is_valid(self):
        """Check if the API key is valid (active and not expired)"""
        return self.is_active and not self.is_expired()


class UserPreferences(models.Model):
    """User preferences and settings"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='preferences',
        primary_key=True
    )

    # Notification preferences
    email_notifications = models.BooleanField(default=True, help_text="Receive email notifications")
    push_notifications = models.BooleanField(default=True, help_text="Receive push notifications")
    indexing_notifications = models.BooleanField(default=True, help_text="Notifications when indexing completes")
    chatbot_notifications = models.BooleanField(default=True, help_text="Notifications about chatbot activity")
    weekly_digest = models.BooleanField(default=True, help_text="Receive weekly summary emails")

    # UI preferences
    theme = models.CharField(
        max_length=10,
        choices=[
            ('light', 'Light'),
            ('dark', 'Dark'),
            ('system', 'System'),
        ],
        default='system',
        help_text="Preferred UI theme"
    )
    language = models.CharField(max_length=10, default='en', help_text="Preferred language")
    timezone = models.CharField(max_length=50, default='UTC', help_text="User timezone")

    # Feature preferences
    enable_analytics = models.BooleanField(default=True, help_text="Enable analytics tracking")
    enable_tooltips = models.BooleanField(default=True, help_text="Show helpful tooltips")
    compact_mode = models.BooleanField(default=False, help_text="Use compact UI mode")

    # Onboarding
    onboarding_completed = models.BooleanField(default=False, help_text="Has completed onboarding")
    tour_completed = models.BooleanField(default=False, help_text="Has completed product tour")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_preferences'
        verbose_name = 'User Preferences'
        verbose_name_plural = 'User Preferences'

    def __str__(self):
        return f"Preferences for {self.user.email}"


class UserFeedback(BaseModel):
    """User feedback about the application"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedback_submissions')
    org_id = models.UUIDField(null=True, blank=True, help_text="Organization context if applicable")

    rating = models.CharField(
        max_length=20,
        choices=[
            ('poor', 'Poor'),
            ('average', 'Average'),
            ('good', 'Good'),
            ('excellent', 'Excellent'),
        ],
        help_text="Overall experience rating"
    )
    comments = models.TextField(help_text="User comments and suggestions")
    allow_contact = models.BooleanField(default=False, help_text="User allows follow-up contact")

    # Additional metadata
    page_url = models.CharField(max_length=500, null=True, blank=True, help_text="Page where feedback was submitted")
    user_agent = models.CharField(max_length=500, null=True, blank=True, help_text="Browser user agent")

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('new', 'New'),
            ('reviewed', 'Reviewed'),
            ('in_progress', 'In Progress'),
            ('resolved', 'Resolved'),
            ('archived', 'Archived'),
        ],
        default='new'
    )
    admin_notes = models.TextField(null=True, blank=True, help_text="Internal notes from admin")

    class Meta:
        db_table = 'user_feedback'
        verbose_name = 'User Feedback'
        verbose_name_plural = 'User Feedback'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['org_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Feedback from {self.user.email} - {self.rating} ({self.created_at.strftime('%Y-%m-%d')})"


class SupportRequest(BaseModel):
    """User support requests from help center"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='support_requests')
    org_id = models.UUIDField(null=True, blank=True, help_text="Organization context if applicable")

    category = models.CharField(
        max_length=20,
        choices=[
            ('account', 'Account & Billing'),
            ('technical', 'Technical Issue'),
            ('feature', 'Feature Request'),
            ('other', 'Other'),
        ],
        help_text="Request category"
    )
    subject = models.CharField(max_length=255, help_text="Brief summary of the issue")
    description = models.TextField(help_text="Detailed description of the request")

    # Additional metadata
    page_url = models.CharField(max_length=500, null=True, blank=True, help_text="Page where request was submitted")
    user_agent = models.CharField(max_length=500, null=True, blank=True, help_text="Browser user agent")

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('new', 'New'),
            ('in_progress', 'In Progress'),
            ('waiting_user', 'Waiting for User'),
            ('resolved', 'Resolved'),
            ('closed', 'Closed'),
        ],
        default='new'
    )
    priority = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('urgent', 'Urgent'),
        ],
        default='medium'
    )
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_support_requests', help_text="Staff member assigned to this request")
    admin_notes = models.TextField(null=True, blank=True, help_text="Internal notes from support staff")
    resolved_at = models.DateTimeField(null=True, blank=True, help_text="When the request was resolved")

    class Meta:
        db_table = 'support_requests'
        verbose_name = 'Support Request'
        verbose_name_plural = 'Support Requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['org_id']),
            models.Index(fields=['status']),
            models.Index(fields=['priority']),
            models.Index(fields=['category']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.category.title()} - {self.subject} ({self.user.email})"
