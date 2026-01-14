"""
Payment URL Configuration.
"""

from django.urls import path
from apps.payments.views import (
    PricingView,
    SubscriptionView,
    CheckoutSessionView,
    PortalSessionView,
    CancelSubscriptionView,
    InvoicesView,
)
from apps.payments.webhooks import StripeWebhookView

app_name = 'payments'

urlpatterns = [
    # Pricing (public tier info)
    path('pricing/', PricingView.as_view(), name='pricing'),
    
    # Subscription management
    path('subscription/', SubscriptionView.as_view(), name='subscription'),
    path('subscription/cancel/', CancelSubscriptionView.as_view(), name='cancel-subscription'),
    
    # Checkout
    path('checkout/', CheckoutSessionView.as_view(), name='checkout'),
    
    # Customer Portal
    path('portal/', PortalSessionView.as_view(), name='portal'),
    
    # Invoices
    path('invoices/', InvoicesView.as_view(), name='invoices'),
    
    # Stripe Webhook (no auth required - verified by signature)
    path('webhook/', StripeWebhookView.as_view(), name='webhook'),
]
