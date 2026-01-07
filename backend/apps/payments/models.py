"""
Payment models for Stripe integration.

These models store payment-related data locally for:
- Audit trail and history
- Webhook event deduplication
- Invoice records
"""

import uuid
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel


class PaymentEvent(BaseModel):
    """
    Track Stripe webhook events for idempotency and audit.
    
    Prevents duplicate processing of the same webhook event.
    """
    stripe_event_id = models.CharField(
        max_length=255, 
        unique=True,
        help_text="Stripe event ID for deduplication"
    )
    event_type = models.CharField(
        max_length=100,
        help_text="Stripe event type (e.g., 'checkout.session.completed')"
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_events'
    )
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    raw_data = models.JSONField(
        default=dict,
        help_text="Raw Stripe event payload for debugging"
    )

    class Meta:
        db_table = 'payment_events'
        verbose_name = 'Payment Event'
        verbose_name_plural = 'Payment Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stripe_event_id']),
            models.Index(fields=['event_type']),
            models.Index(fields=['processed']),
            models.Index(fields=['organization']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.stripe_event_id}"

    def mark_processed(self, error=None):
        """Mark event as processed with optional error"""
        self.processed = True
        self.processed_at = timezone.now()
        if error:
            self.error_message = str(error)
        self.save(update_fields=['processed', 'processed_at', 'error_message', 'updated_at'])


class Invoice(BaseModel):
    """
    Store invoice records from Stripe.
    
    Provides local access to invoice history without hitting Stripe API.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    stripe_invoice_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Stripe invoice ID"
    )
    stripe_customer_id = models.CharField(max_length=255)
    
    # Invoice details
    number = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=[
            ('draft', 'Draft'),
            ('open', 'Open'),
            ('paid', 'Paid'),
            ('void', 'Void'),
            ('uncollectible', 'Uncollectible'),
        ],
        default='open'
    )
    
    # Amounts (in cents)
    subtotal = models.IntegerField(default=0)
    tax = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    amount_paid = models.IntegerField(default=0)
    amount_due = models.IntegerField(default=0)
    currency = models.CharField(max_length=10, default='usd')
    
    # Dates
    invoice_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # URLs
    hosted_invoice_url = models.URLField(max_length=500, null=True, blank=True)
    invoice_pdf = models.URLField(max_length=500, null=True, blank=True)
    
    # Metadata
    description = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        db_table = 'invoices'
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'
        ordering = ['-invoice_date']
        indexes = [
            models.Index(fields=['organization']),
            models.Index(fields=['stripe_invoice_id']),
            models.Index(fields=['status']),
            models.Index(fields=['invoice_date']),
        ]

    def __str__(self):
        return f"Invoice {self.number or self.stripe_invoice_id} - {self.organization.name}"

    @property
    def total_dollars(self):
        """Return total in dollars"""
        return self.total / 100

    @property
    def is_paid(self):
        return self.status == 'paid'


class CheckoutSession(BaseModel):
    """
    Track checkout sessions for correlation.
    
    Links Stripe checkout sessions to organizations and tracks completion.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='checkout_sessions'
    )
    stripe_session_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Stripe Checkout Session ID"
    )
    
    # Session details
    target_plan = models.CharField(
        max_length=20,
        choices=[
            ('basic', 'Basic'),
            ('premium', 'Premium'),
            ('enterprise', 'Enterprise'),
        ]
    )
    stripe_price_id = models.CharField(max_length=255)
    
    # Status
    status = models.CharField(
        max_length=50,
        choices=[
            ('pending', 'Pending'),
            ('complete', 'Complete'),
            ('expired', 'Expired'),
        ],
        default='pending'
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # URLs for redirect
    success_url = models.URLField(max_length=500)
    cancel_url = models.URLField(max_length=500)
    
    # Metadata
    metadata = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'checkout_sessions'
        verbose_name = 'Checkout Session'
        verbose_name_plural = 'Checkout Sessions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization']),
            models.Index(fields=['stripe_session_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Checkout {self.target_plan} - {self.organization.name}"

    def mark_complete(self):
        """Mark session as complete"""
        self.status = 'complete'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
