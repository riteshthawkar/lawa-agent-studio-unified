"""
Payment Serializers for API responses.
"""

from rest_framework import serializers


class CheckoutSessionRequestSerializer(serializers.Serializer):
    """Request serializer for creating checkout session"""
    plan = serializers.ChoiceField(
        choices=['basic', 'premium', 'enterprise'],
        help_text="Target subscription plan"
    )
    success_url = serializers.URLField(
        required=False,
        help_text="URL to redirect after successful checkout"
    )
    cancel_url = serializers.URLField(
        required=False,
        help_text="URL to redirect if checkout is cancelled"
    )


class CheckoutSessionResponseSerializer(serializers.Serializer):
    """Response serializer for checkout session"""
    session_id = serializers.CharField()
    checkout_url = serializers.URLField()


class PortalSessionRequestSerializer(serializers.Serializer):
    """Request serializer for creating portal session"""
    return_url = serializers.URLField(
        required=False,
        help_text="URL to redirect after portal session"
    )


class PortalSessionResponseSerializer(serializers.Serializer):
    """Response serializer for portal session"""
    portal_url = serializers.URLField()


class SubscriptionSerializer(serializers.Serializer):
    """Serializer for subscription details"""
    plan = serializers.CharField()
    status = serializers.CharField()
    current_period_start = serializers.DateTimeField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    cancel_at_period_end = serializers.BooleanField(default=False)
    trial_ends_at = serializers.DateTimeField(allow_null=True)
    stripe_configured = serializers.BooleanField()
    stripe_configured = serializers.BooleanField()
    has_payment_method = serializers.BooleanField(default=False)
    limits = serializers.DictField(required=False, help_text="Usage limits for the plan")


class CancelSubscriptionRequestSerializer(serializers.Serializer):
    """Request serializer for cancelling subscription"""
    cancel_immediately = serializers.BooleanField(
        default=False,
        help_text="If true, cancel immediately. Otherwise, cancel at period end."
    )


class InvoiceSerializer(serializers.Serializer):
    """Serializer for invoice data"""
    id = serializers.CharField()
    number = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    total = serializers.IntegerField()
    total_dollars = serializers.SerializerMethodField()
    currency = serializers.CharField()
    created = serializers.IntegerField()
    paid = serializers.BooleanField()
    hosted_invoice_url = serializers.URLField(allow_null=True)
    invoice_pdf = serializers.URLField(allow_null=True)
    
    def get_total_dollars(self, obj):
        return obj.get('total', 0) / 100


class PricingTierSerializer(serializers.Serializer):
    """Serializer for pricing tier information"""
    id = serializers.CharField()
    name = serializers.CharField()
    price = serializers.IntegerField(help_text="Price in cents")
    price_display = serializers.CharField()
    interval = serializers.CharField()
    features = serializers.ListField(child=serializers.CharField())
    limits = serializers.DictField()
    is_current = serializers.BooleanField()
    popular = serializers.BooleanField(default=False)
