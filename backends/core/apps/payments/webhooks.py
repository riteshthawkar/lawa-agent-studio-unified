"""
Stripe Webhook Handler.

CRITICAL SECURITY: This module handles Stripe webhooks with:
- Signature verification (REQUIRED)
- Idempotent event processing
- Proper error handling and logging
"""

import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.views import View

from apps.payments.stripe_service import StripeService, StripeNotConfiguredError
from apps.payments.models import PaymentEvent, Invoice

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(require_POST, name='dispatch')
class StripeWebhookView(View):
    """
    Handle Stripe webhook events.
    
    This view receives webhook events from Stripe and processes them.
    All events are verified with signature before processing.
    """
    
    def post(self, request):
        """Process incoming webhook"""
        # Check if Stripe is configured
        if not StripeService.is_configured():
            logger.warning("Webhook received but Stripe is not configured")
            return HttpResponse("Stripe not configured", status=503)
        
        # Get signature header
        signature = request.META.get('HTTP_STRIPE_SIGNATURE')
        if not signature:
            logger.warning("Webhook received without signature header")
            return HttpResponse("Missing signature", status=400)
        
        # Verify signature and construct event
        try:
            event = StripeService.verify_webhook_signature(
                request.body,
                signature
            )
        except ValueError as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return HttpResponse("Invalid signature", status=400)
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return HttpResponse("Webhook error", status=400)
        
        # Check for duplicate event (idempotency)
        event_id = event.get('id')
        if PaymentEvent.objects.filter(stripe_event_id=event_id, processed=True).exists():
            logger.info(f"Duplicate event {event_id} - already processed")
            return HttpResponse("Event already processed", status=200)
        
        # Store event for audit
        payment_event, created = PaymentEvent.objects.get_or_create(
            stripe_event_id=event_id,
            defaults={
                'event_type': event.type,
                'raw_data': dict(event),
            }
        )
        
        if not created and payment_event.processed:
            logger.info(f"Duplicate event {event_id} - already processed")
            return HttpResponse("Event already processed", status=200)
        
        # Process the event
        try:
            self.handle_event(event, payment_event)
            payment_event.mark_processed()
            logger.info(f"Successfully processed event {event_id} ({event.type})")
            return HttpResponse("Event processed", status=200)
            
        except Exception as e:
            logger.error(f"Failed to process event {event_id}: {e}")
            payment_event.mark_processed(error=str(e))
            # Return 200 to prevent Stripe from retrying
            # We log the error for manual investigation
            return HttpResponse("Event processed with error", status=200)
    
    def handle_event(self, event, payment_event):
        """
        Route event to appropriate handler.
        """
        event_type = event.type
        
        handlers = {
            'checkout.session.completed': self.handle_checkout_completed,
            'customer.subscription.created': self.handle_subscription_created,
            'customer.subscription.updated': self.handle_subscription_updated,
            'customer.subscription.deleted': self.handle_subscription_deleted,
            'invoice.payment_succeeded': self.handle_invoice_paid,
            'invoice.payment_failed': self.handle_invoice_failed,
            'customer.updated': self.handle_customer_updated,
        }
        
        handler = handlers.get(event_type)
        if handler:
            handler(event, payment_event)
        else:
            logger.info(f"Unhandled event type: {event_type}")
    
    def handle_checkout_completed(self, event, payment_event):
        """
        Handle checkout.session.completed event.
        
        This is triggered when a customer completes checkout.
        """
        from apps.payments.models import CheckoutSession
        from apps.organizations.models import Organization
        
        session = event.data.object
        
        # Update local checkout session
        try:
            checkout = CheckoutSession.objects.get(stripe_session_id=session.id)
            checkout.mark_complete()
            payment_event.organization = checkout.organization
            payment_event.save(update_fields=['organization', 'updated_at'])
        except CheckoutSession.DoesNotExist:
            logger.warning(f"Checkout session {session.id} not found locally")
        
        # If subscription was created, sync it
        if session.subscription:
            import stripe
            stripe_sub = stripe.Subscription.retrieve(session.subscription)
            StripeService.sync_subscription_from_stripe(stripe_sub)
        
        logger.info(f"Checkout completed: {session.id}")
    
    def handle_subscription_created(self, event, payment_event):
        """Handle customer.subscription.created event."""
        subscription = event.data.object
        StripeService.sync_subscription_from_stripe(subscription)
        
        # Link organization to event
        org_id = subscription.metadata.get('organization_id')
        if org_id:
            from apps.organizations.models import Organization
            try:
                org = Organization.objects.get(id=org_id)
                payment_event.organization = org
                payment_event.save(update_fields=['organization', 'updated_at'])
            except Organization.DoesNotExist:
                pass
        
        logger.info(f"Subscription created: {subscription.id}")
    
    def handle_subscription_updated(self, event, payment_event):
        """Handle customer.subscription.updated event."""
        subscription = event.data.object
        StripeService.sync_subscription_from_stripe(subscription)
        
        # Check for specific changes
        previous = event.data.previous_attributes
        
        if 'status' in previous:
            logger.info(f"Subscription status changed: {previous['status']} -> {subscription.status}")
        
        if 'cancel_at_period_end' in previous:
            if subscription.cancel_at_period_end:
                logger.info(f"Subscription scheduled for cancellation: {subscription.id}")
            else:
                logger.info(f"Subscription cancellation reverted: {subscription.id}")
        
        logger.info(f"Subscription updated: {subscription.id}")
    
    def handle_subscription_deleted(self, event, payment_event):
        """Handle customer.subscription.deleted event."""
        subscription = event.data.object
        
        from apps.usage.models import Subscription
        from apps.organizations.models import Organization
        
        org_id = subscription.metadata.get('organization_id')
        if org_id:
            try:
                org = Organization.objects.get(id=org_id)
                payment_event.organization = org
                payment_event.save(update_fields=['organization', 'updated_at'])
                
                # Update local subscription
                try:
                    local_sub = org.subscription
                    local_sub.plan = 'free'
                    local_sub.status = 'cancelled'
                    local_sub.stripe_subscription_id = None
                    local_sub.save()
                except Subscription.DoesNotExist:
                    pass
                
                # Revert organization plan
                org.plan_tier = 'trial'
                org.save(update_fields=['plan_tier', 'updated_at'])
                
            except Organization.DoesNotExist:
                pass
        
        logger.info(f"Subscription deleted: {subscription.id}")
    
    def handle_invoice_paid(self, event, payment_event):
        """Handle invoice.payment_succeeded event."""
        invoice = event.data.object
        
        # Store invoice locally
        from apps.organizations.models import Organization
        from datetime import datetime
        from django.utils import timezone
        
        org_id = invoice.metadata.get('organization_id') if invoice.metadata else None
        
        # Try to find organization from customer
        org = None
        if org_id:
            try:
                org = Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                pass
        
        if not org and invoice.customer:
            from apps.usage.models import Subscription
            try:
                sub = Subscription.objects.get(stripe_customer_id=invoice.customer)
                org = sub.organization
            except Subscription.DoesNotExist:
                pass
        
        if org:
            Invoice.objects.update_or_create(
                stripe_invoice_id=invoice.id,
                defaults={
                    'organization': org,
                    'stripe_customer_id': invoice.customer,
                    'number': invoice.number,
                    'status': 'paid',
                    'subtotal': invoice.subtotal,
                    'tax': invoice.tax or 0,
                    'total': invoice.total,
                    'amount_paid': invoice.amount_paid,
                    'amount_due': invoice.amount_due,
                    'currency': invoice.currency,
                    'invoice_date': timezone.datetime.fromtimestamp(invoice.created, tz=timezone.utc) if invoice.created else None,
                    'paid_at': timezone.now(),
                    'hosted_invoice_url': invoice.hosted_invoice_url,
                    'invoice_pdf': invoice.invoice_pdf,
                }
            )
            payment_event.organization = org
            payment_event.save(update_fields=['organization', 'updated_at'])
        
        logger.info(f"Invoice paid: {invoice.id}")
    
    def handle_invoice_failed(self, event, payment_event):
        """
        Handle invoice.payment_failed event.
        
        TODO: Send email notification to customer about failed payment.
        """
        invoice = event.data.object
        
        logger.warning(f"Invoice payment failed: {invoice.id}")
        
        # TODO: Send notification email
        # TODO: Update subscription status to past_due
    
    def handle_customer_updated(self, event, payment_event):
        """Handle customer.updated event."""
        customer = event.data.object
        
        from apps.usage.models import Subscription
        
        # Update billing email if changed
        try:
            subscription = Subscription.objects.get(stripe_customer_id=customer.id)
            if customer.email and subscription.billing_email != customer.email:
                subscription.billing_email = customer.email
                subscription.save(update_fields=['billing_email', 'updated_at'])
                logger.info(f"Updated billing email for customer {customer.id}")
        except Subscription.DoesNotExist:
            pass
