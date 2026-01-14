import uuid
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel


class UsageEvent(BaseModel):
    """Usage event tracking"""
    org_id = models.UUIDField()
    site_id = models.UUIDField(null=True, blank=True)
    chatbot_id = models.UUIDField(null=True, blank=True)
    session_id = models.UUIDField(null=True, blank=True)
    type = models.CharField(
        max_length=20,
        choices=[
            ('embedding', 'Embedding'),
            ('query', 'Query'),
            ('index_write', 'Index Write'),
            ('chat', 'Chat'),
        ]
    )
    units = models.IntegerField(default=1)
    cost_cents = models.IntegerField(default=0)
    meta = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'usage_events'
        verbose_name = 'Usage Event'
        verbose_name_plural = 'Usage Events'
        indexes = [
            models.Index(fields=['org_id']),
            models.Index(fields=['type']),
            models.Index(fields=['occurred_at']),
            # Composite index for optimized quota checking
            models.Index(fields=['org_id', 'type', 'occurred_at'], name='usage_events_quota_idx'),
        ]

    def __str__(self):
        return f"{self.type} - {self.org_id}"


class Quota(BaseModel):
    """Quota management"""
    org_id = models.UUIDField()
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    limits = models.JSONField(default=dict)  # max_pages, max_vectors, monthly_cost_cap, concurrent_jobs
    usage = models.JSONField(default=dict)  # Current usage tracking

    class Meta:
        db_table = 'quotas'
        verbose_name = 'Quota'
        verbose_name_plural = 'Quotas'
        indexes = [
            models.Index(fields=['org_id']),
            models.Index(fields=['period_start', 'period_end']),
        ]

    def __str__(self):
        return f"Quota {self.org_id} ({self.period_start} - {self.period_end})"


class Subscription(BaseModel):
    """Subscription and billing management"""
    organization = models.OneToOneField(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.CharField(
        max_length=20,
        choices=[
            ('basic', 'Basic'),        # Free tier
            ('premium', 'Premium'),    # Paid tier
            ('enterprise', 'Enterprise'),  # Custom/contact us
        ],
        default='basic'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('trialing', 'Trialing'),
            ('past_due', 'Past Due'),
            ('cancelled', 'Cancelled'),
            ('paused', 'Paused'),
        ],
        default='active'
    )
    
    # Trial management
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    
    # Billing periods
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)
    
    # Feature toggles (for custom overrides)
    features_override = models.JSONField(
        default=dict,
        help_text="Custom feature toggles that override tier defaults"
    )
    
    # Billing metadata
    billing_email = models.EmailField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, null=True, blank=True)
    
    # Analytics retention
    analytics_retention_days = models.IntegerField(
        null=True,
        blank=True,
        help_text="Override default retention based on tier"
    )

    class Meta:
        db_table = 'subscriptions'
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'
        indexes = [
            models.Index(fields=['organization']),
            models.Index(fields=['plan']),
            models.Index(fields=['status']),
            models.Index(fields=['trial_ends_at']),
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.plan} ({self.status})"
    
    def is_trial_active(self):
        """Check if trial is still active"""
        if self.status == 'trialing' and self.trial_ends_at:
            return timezone.now() < self.trial_ends_at
        return False
    
    def get_effective_plan(self):
        """Get the effective plan (considering trial status)"""
        if self.is_trial_active():
            return 'premium'  # Trial gets premium tier features
        return self.plan


class UpgradeInterest(BaseModel):
    """
    Track user interest in upgrading to paid plans.

    Used for:
    - Waitlist functionality before Stripe is configured
    - Lead scoring and prioritization
    - Understanding user demand for different tiers
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='upgrade_interests'
    )
    user = models.ForeignKey(
        'lawa_auth.User',
        on_delete=models.CASCADE,
        related_name='upgrade_interests'
    )
    interested_plan = models.CharField(
        max_length=20,
        choices=[
            ('premium', 'Premium'),
            ('enterprise', 'Enterprise'),
        ]
    )
    source = models.CharField(
        max_length=50,
        choices=[
            ('billing_page', 'Billing Page'),
            ('upgrade_prompt', 'Upgrade Prompt'),
            ('limit_reached', 'Limit Reached'),
            ('feature_locked', 'Feature Locked'),
            ('usage_page', 'Usage Page'),
            ('other', 'Other'),
        ],
        default='billing_page'
    )
    email = models.EmailField(
        help_text="Contact email for waitlist notifications"
    )
    company_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Company name for enterprise inquiries"
    )
    message = models.TextField(
        blank=True,
        help_text="Optional message or requirements"
    )
    metadata = models.JSONField(
        default=dict,
        help_text="Additional context (current usage, features requested, etc.)"
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('contacted', 'Contacted'),
            ('converted', 'Converted'),
            ('declined', 'Declined'),
        ],
        default='pending'
    )
    contacted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(
        blank=True,
        help_text="Internal notes for sales/admin"
    )

    class Meta:
        db_table = 'upgrade_interests'
        verbose_name = 'Upgrade Interest'
        verbose_name_plural = 'Upgrade Interests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization']),
            models.Index(fields=['interested_plan']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.email} - {self.interested_plan} ({self.status})"
