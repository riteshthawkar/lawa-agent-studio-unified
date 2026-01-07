"""
Stripe Service - Core integration with Stripe API.

This module handles all Stripe API interactions with proper security:
- Webhook signature verification
- Idempotency keys for payment operations
- Error handling with proper logging
- Graceful fallbacks when Stripe is not configured
"""

import logging
import time
from typing import Optional, Dict, Any
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Check if Stripe is configured
STRIPE_CONFIGURED = bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))

if STRIPE_CONFIGURED:
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = getattr(settings, 'STRIPE_API_VERSION', '2023-10-16')


class StripeNotConfiguredError(Exception):
    """Raised when Stripe is not configured"""
    pass


class StripeService:
    """
    Service class for Stripe operations.
    
    All methods check for Stripe configuration before making API calls.
    """
    
    @classmethod
    def is_configured(cls) -> bool:
        """Check if Stripe is properly configured"""
        return STRIPE_CONFIGURED and bool(settings.STRIPE_SECRET_KEY)
    
    @classmethod
    def require_configuration(cls):
        """Raise error if Stripe is not configured"""
        if not cls.is_configured():
            raise StripeNotConfiguredError(
                "Stripe is not configured. Please set STRIPE_SECRET_KEY in environment variables."
            )
    
    # ==================== Customer Management ====================
    
    @classmethod
    def get_or_create_customer(cls, organization, email: str) -> str:
        """
        Get existing Stripe customer or create new one.
        
        Returns the Stripe customer ID.
        """
        cls.require_configuration()
        
        from apps.usage.models import Subscription
        
        # Check if subscription already has a customer ID
        try:
            subscription = organization.subscription
            if subscription.stripe_customer_id:
                return subscription.stripe_customer_id
        except Subscription.DoesNotExist:
            subscription = Subscription.objects.create(
                organization=organization,
                plan='basic',  # basic is the free tier
                status='active'
            )
        
        # Create new Stripe customer
        try:
            customer = stripe.Customer.create(
                email=email,
                name=organization.name,
                metadata={
                    'organization_id': str(organization.id),
                    'organization_name': organization.name,
                },
                idempotency_key=f"customer_{organization.id}"
            )
            
            # Save customer ID
            subscription.stripe_customer_id = customer.id
            subscription.billing_email = email
            subscription.save(update_fields=['stripe_customer_id', 'billing_email', 'updated_at'])
            
            logger.info(f"Created Stripe customer {customer.id} for organization {organization.id}")
            return customer.id
            
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            raise
    
    # ==================== Checkout Sessions ====================
    
    @classmethod
    def create_checkout_session(
        cls,
        organization,
        price_id: str,
        plan: str,
        success_url: str,
        cancel_url: str,
        customer_email: str,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout Session for subscription.
        
        Returns dict with session_id and checkout_url.
        """
        cls.require_configuration()
        
        from apps.payments.models import CheckoutSession
        
        # Get or create customer
        customer_id = cls.get_or_create_customer(organization, customer_email)
        
        # Generate idempotency key
        idempotency_key = f"checkout_{organization.id}_{price_id}_{int(time.time())}"
        
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                mode='subscription',
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=cancel_url,
                metadata={
                    'organization_id': str(organization.id),
                    'target_plan': plan,
                },
                subscription_data={
                    'metadata': {
                        'organization_id': str(organization.id),
                        'plan': plan,
                    }
                },
                allow_promotion_codes=True,
                billing_address_collection='auto',
                idempotency_key=idempotency_key,
            )
            
            # Store checkout session locally
            CheckoutSession.objects.create(
                organization=organization,
                stripe_session_id=session.id,
                target_plan=plan,
                stripe_price_id=price_id,
                success_url=success_url,
                cancel_url=cancel_url,
                expires_at=timezone.now() + timezone.timedelta(hours=24),
                metadata={'idempotency_key': idempotency_key}
            )
            
            logger.info(f"Created checkout session {session.id} for organization {organization.id}")
            
            return {
                'session_id': session.id,
                'checkout_url': session.url,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create checkout session: {e}")
            raise
    
    # ==================== Customer Portal ====================
    
    @classmethod
    def create_portal_session(cls, organization, return_url: str) -> Dict[str, Any]:
        """
        Create a Stripe Customer Portal session.
        
        Allows customers to manage their subscription, payment methods, etc.
        """
        cls.require_configuration()
        
        from apps.usage.models import Subscription
        
        try:
            subscription = organization.subscription
            if not subscription.stripe_customer_id:
                raise ValueError("Organization does not have a Stripe customer ID")
        except Subscription.DoesNotExist:
            raise ValueError("Organization does not have a subscription")
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=subscription.stripe_customer_id,
                return_url=return_url,
            )
            
            logger.info(f"Created portal session for organization {organization.id}")
            
            return {
                'portal_url': session.url,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create portal session: {e}")
            raise
    
    # ==================== Subscription Management ====================
    
    @classmethod
    def get_subscription(cls, organization) -> Optional[Dict[str, Any]]:
        """
        Get current subscription details from Stripe.
        """
        cls.require_configuration()
        
        from apps.usage.models import Subscription
        
        try:
            subscription = organization.subscription
            if not subscription.stripe_subscription_id:
                return None
        except Subscription.DoesNotExist:
            return None
        
        try:
            stripe_sub = stripe.Subscription.retrieve(
                subscription.stripe_subscription_id,
                expand=['latest_invoice', 'default_payment_method']
            )
            
            return {
                'id': stripe_sub.id,
                'status': stripe_sub.status,
                'current_period_start': stripe_sub.current_period_start,
                'current_period_end': stripe_sub.current_period_end,
                'cancel_at_period_end': stripe_sub.cancel_at_period_end,
                'canceled_at': stripe_sub.canceled_at,
                'plan': subscription.plan,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Failed to get subscription: {e}")
            raise
    
    @classmethod
    def cancel_subscription(cls, organization, at_period_end: bool = True) -> Dict[str, Any]:
        """
        Cancel a subscription.
        
        By default, cancels at period end (gives customer access until paid period ends).
        """
        cls.require_configuration()
        
        from apps.usage.models import Subscription
        
        try:
            subscription = organization.subscription
            if not subscription.stripe_subscription_id:
                raise ValueError("No active subscription to cancel")
        except Subscription.DoesNotExist:
            raise ValueError("Organization does not have a subscription")
        
        try:
            if at_period_end:
                # Cancel at end of billing period
                stripe_sub = stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                # Cancel immediately
                stripe_sub = stripe.Subscription.cancel(
                    subscription.stripe_subscription_id,
                )
            
            # Update local subscription
            subscription.status = 'cancelled' if not at_period_end else subscription.status
            subscription.save(update_fields=['status', 'updated_at'])
            
            logger.info(f"Cancelled subscription for organization {organization.id}")
            
            return {
                'status': stripe_sub.status,
                'cancel_at_period_end': stripe_sub.cancel_at_period_end,
                'canceled_at': stripe_sub.canceled_at,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Failed to cancel subscription: {e}")
            raise
    
    # ==================== Invoice Management ====================
    
    @classmethod
    def list_invoices(cls, organization, limit: int = 10) -> list:
        """
        List invoices for an organization.
        """
        cls.require_configuration()
        
        from apps.usage.models import Subscription
        
        try:
            subscription = organization.subscription
            if not subscription.stripe_customer_id:
                return []
        except Subscription.DoesNotExist:
            return []
        
        try:
            invoices = stripe.Invoice.list(
                customer=subscription.stripe_customer_id,
                limit=limit,
            )
            
            return [{
                'id': inv.id,
                'number': inv.number,
                'status': inv.status,
                'total': inv.total,
                'currency': inv.currency,
                'created': inv.created,
                'paid': inv.paid,
                'hosted_invoice_url': inv.hosted_invoice_url,
                'invoice_pdf': inv.invoice_pdf,
            } for inv in invoices.data]
            
        except stripe.error.StripeError as e:
            logger.error(f"Failed to list invoices: {e}")
            raise
    
    # ==================== Webhook Signature Verification ====================
    
    @classmethod
    def verify_webhook_signature(cls, payload: bytes, signature: str) -> Dict[str, Any]:
        """
        Verify webhook signature and construct event.
        
        CRITICAL SECURITY: Always verify webhook signatures in production.
        """
        cls.require_configuration()
        
        webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
        if not webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
        
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                webhook_secret
            )
            return event
            
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Webhook signature verification failed: {e}")
            raise
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {e}")
            raise
    
    # ==================== Sync Helpers ====================
    
    @classmethod
    def sync_subscription_from_stripe(cls, stripe_subscription) -> None:
        """
        Sync local subscription data from Stripe subscription object.
        """
        from apps.usage.models import Subscription
        from apps.organizations.models import Organization
        
        org_id = stripe_subscription.metadata.get('organization_id')
        if not org_id:
            logger.warning(f"Subscription {stripe_subscription.id} has no organization_id in metadata")
            return
        
        try:
            organization = Organization.objects.get(id=org_id)
            subscription, created = Subscription.objects.get_or_create(
                organization=organization,
                defaults={'plan': 'basic', 'status': 'active'}  # basic is the free tier
            )
            
            # Map Stripe status to local status
            status_map = {
                'active': 'active',
                'trialing': 'trialing',
                'past_due': 'past_due',
                'canceled': 'cancelled',
                'unpaid': 'past_due',
                'incomplete': 'active',
                'incomplete_expired': 'cancelled',
            }
            
            # Get plan from metadata (basic is the free tier)
            plan = stripe_subscription.metadata.get('plan', 'basic')
            
            # Update subscription
            subscription.stripe_subscription_id = stripe_subscription.id
            subscription.plan = plan
            subscription.status = status_map.get(stripe_subscription.status, 'active')
            subscription.current_period_start = timezone.datetime.fromtimestamp(
                stripe_subscription.current_period_start, tz=timezone.utc
            )
            subscription.current_period_end = timezone.datetime.fromtimestamp(
                stripe_subscription.current_period_end, tz=timezone.utc
            )
            subscription.save()
            
            # Also update organization plan_tier (now matches subscription plan names)
            # basic = free tier, premium = paid tier, enterprise = custom
            organization.plan_tier = plan if plan in ['basic', 'premium', 'enterprise'] else 'basic'
            organization.save(update_fields=['plan_tier', 'updated_at'])
            
            logger.info(f"Synced subscription for organization {org_id}: plan={plan}, status={subscription.status}")
            
        except Organization.DoesNotExist:
            logger.error(f"Organization {org_id} not found for subscription sync")
        except Exception as e:
            logger.error(f"Failed to sync subscription: {e}")
            raise


# Convenience function for checking configuration
def stripe_is_configured() -> bool:
    """Check if Stripe is configured"""
    return StripeService.is_configured()
