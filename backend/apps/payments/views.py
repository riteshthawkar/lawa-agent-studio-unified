"""
Payment Views - REST API endpoints for Stripe integration.

All endpoints require authentication and organization context.
"""

import logging
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.payments.serializers import (
    CheckoutSessionRequestSerializer,
    CheckoutSessionResponseSerializer,
    PortalSessionRequestSerializer,
    PortalSessionResponseSerializer,
    SubscriptionSerializer,
    CancelSubscriptionRequestSerializer,
    InvoiceSerializer,
    PricingTierSerializer,
)
from apps.payments.stripe_service import StripeService, StripeNotConfiguredError
from apps.usage.models import Subscription
from apps.usage.tier_config import TIER_FEATURES

logger = logging.getLogger(__name__)


class StripeConfigCheckMixin:
    """Mixin to check if Stripe is configured"""
    
    def check_stripe_configured(self):
        """Return error response if Stripe is not configured"""
        if not StripeService.is_configured():
            return Response({
                'error': 'stripe_not_configured',
                'message': 'Payment processing is not configured. Please contact support.',
                'configured': False,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return None


class PricingView(APIView):
    """
    Get pricing information for all tiers.
    
    This endpoint is public and doesn't require Stripe configuration.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Get pricing tiers",
        description="Returns pricing information for all subscription tiers",
        responses={200: PricingTierSerializer(many=True)},
        tags=['Payments']
    )
    def get(self, request):
        """Get all pricing tiers"""
        # Get current user's organization and plan
        org = getattr(request, 'org', None)
        current_plan = 'basic'  # basic is the free tier

        if org:
            try:
                subscription = org.subscription
                current_plan = subscription.plan
            except Subscription.DoesNotExist:
                pass

        # Stripe price IDs (from settings or defaults)
        stripe_prices = getattr(settings, 'STRIPE_PRICES', {})

        tiers = [
            {
                'id': 'basic',
                'name': 'Basic',
                'price': 0,
                'price_display': 'Free',
                'interval': 'forever',
                'features': [
                    '1 Project',
                    '1 Chatbot',
                    '100 conversations/day',
                    '5,000 total conversations',
                    '7-day analytics',
                    'Basic insights',
                ],
                'limits': TIER_FEATURES['basic']['limits'],
                'is_current': current_plan == 'basic',
                'popular': False,
                'stripe_price_id': None,
            },
            {
                'id': 'premium',
                'name': 'Premium',
                'price': 4900,  # $49.00 (placeholder - to be decided)
                'price_display': '$49/mo',
                'interval': 'month',
                'features': [
                    '10 Projects',
                    '25 Chatbots',
                    '1,000 conversations/day',
                    'Unlimited total conversations',
                    '90-day analytics',
                    'Advanced insights',
                    'Query categories',
                    'Sentiment analysis',
                    'CSV & JSON export',
                    'Priority support',
                ],
                'limits': TIER_FEATURES['premium']['limits'],
                'is_current': current_plan == 'premium',
                'popular': True,
                'stripe_price_id': stripe_prices.get('premium'),
            },
            {
                'id': 'enterprise',
                'name': 'Enterprise',
                'price': None,
                'price_display': 'Contact Us',
                'interval': 'custom',
                'features': [
                    'Unlimited Projects',
                    'Unlimited Chatbots',
                    'Unlimited conversations',
                    '1-year analytics',
                    'All premium features',
                    'Custom integrations',
                    'Dedicated support',
                    'SLA guarantee',
                ],
                'limits': TIER_FEATURES['enterprise']['limits'],
                'is_current': current_plan == 'enterprise',
                'popular': False,
                'stripe_price_id': None,  # Enterprise is contact-only
            },
        ]

        return Response({
            'tiers': tiers,
            'current_plan': current_plan,
            'stripe_configured': StripeService.is_configured(),
        })


class SubscriptionView(APIView, StripeConfigCheckMixin):
    """
    Get current subscription details.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Get subscription details",
        description="Returns the current subscription status for the organization",
        responses={200: SubscriptionSerializer},
        tags=['Payments']
    )
    def get(self, request):
        """Get current subscription"""
        org = getattr(request, 'org', None)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            subscription = org.subscription
        except Subscription.DoesNotExist:
            subscription = Subscription.objects.create(
                organization=org,
                plan='basic',  # basic is the free tier
                status='active'
            )
        
        data = {
            'plan': subscription.plan,
            'status': subscription.status,
            'current_period_start': subscription.current_period_start,
            'current_period_end': subscription.current_period_end,
            'cancel_at_period_end': getattr(subscription, 'cancel_at_period_end', False),
            'trial_ends_at': subscription.trial_ends_at,
            'stripe_configured': StripeService.is_configured(),
            'has_payment_method': bool(subscription.stripe_customer_id),
        }
        
        return Response(data)


class CheckoutSessionView(APIView, StripeConfigCheckMixin):
    """
    Create a Stripe Checkout Session for upgrading subscription.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Create checkout session",
        description="Creates a Stripe Checkout Session for subscription upgrade",
        request=CheckoutSessionRequestSerializer,
        responses={
            200: CheckoutSessionResponseSerializer,
            400: OpenApiResponse(description="Invalid request"),
            503: OpenApiResponse(description="Stripe not configured"),
        },
        tags=['Payments']
    )
    def post(self, request):
        """Create checkout session"""
        # Check Stripe configuration
        error_response = self.check_stripe_configured()
        if error_response:
            return error_response
        
        serializer = CheckoutSessionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        org = getattr(request, 'org', None)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)
        
        plan = serializer.validated_data['plan']
        
        # Get Stripe price ID
        stripe_prices = getattr(settings, 'STRIPE_PRICES', {})
        price_id = stripe_prices.get(plan)
        
        if not price_id:
            return Response({
                'error': 'price_not_configured',
                'message': f'Price for {plan} plan is not configured',
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set URLs
        base_url = request.build_absolute_uri('/').rstrip('/')
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        
        success_url = serializer.validated_data.get('success_url') or f"{frontend_url}/billing/success"
        cancel_url = serializer.validated_data.get('cancel_url') or f"{frontend_url}/billing"
        
        try:
            result = StripeService.create_checkout_session(
                organization=org,
                price_id=price_id,
                plan=plan,
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=request.user.email,
            )
            
            return Response(result)
            
        except StripeNotConfiguredError as e:
            return Response({
                'error': 'stripe_not_configured',
                'message': str(e),
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.error(f"Checkout session error: {e}")
            return Response({
                'error': 'checkout_failed',
                'message': 'Failed to create checkout session. Please try again.',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PortalSessionView(APIView, StripeConfigCheckMixin):
    """
    Create a Stripe Customer Portal session.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Create portal session",
        description="Creates a Stripe Customer Portal session for subscription management",
        request=PortalSessionRequestSerializer,
        responses={
            200: PortalSessionResponseSerializer,
            400: OpenApiResponse(description="Invalid request"),
            503: OpenApiResponse(description="Stripe not configured"),
        },
        tags=['Payments']
    )
    def post(self, request):
        """Create portal session"""
        error_response = self.check_stripe_configured()
        if error_response:
            return error_response
        
        serializer = PortalSessionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        org = getattr(request, 'org', None)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)
        
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        return_url = serializer.validated_data.get('return_url') or f"{frontend_url}/billing"
        
        try:
            result = StripeService.create_portal_session(
                organization=org,
                return_url=return_url,
            )
            
            return Response(result)
            
        except ValueError as e:
            return Response({
                'error': 'portal_failed',
                'message': str(e),
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Portal session error: {e}")
            return Response({
                'error': 'portal_failed',
                'message': 'Failed to create portal session. Please try again.',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CancelSubscriptionView(APIView, StripeConfigCheckMixin):
    """
    Cancel the current subscription.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Cancel subscription",
        description="Cancels the current subscription",
        request=CancelSubscriptionRequestSerializer,
        responses={
            200: OpenApiResponse(description="Subscription cancelled"),
            400: OpenApiResponse(description="Invalid request"),
        },
        tags=['Payments']
    )
    def post(self, request):
        """Cancel subscription"""
        error_response = self.check_stripe_configured()
        if error_response:
            return error_response
        
        serializer = CancelSubscriptionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        org = getattr(request, 'org', None)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)
        
        cancel_immediately = serializer.validated_data.get('cancel_immediately', False)
        
        try:
            result = StripeService.cancel_subscription(
                organization=org,
                at_period_end=not cancel_immediately,
            )
            
            return Response({
                'message': 'Subscription cancelled successfully',
                **result,
            })
            
        except ValueError as e:
            return Response({
                'error': 'cancel_failed',
                'message': str(e),
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Cancel subscription error: {e}")
            return Response({
                'error': 'cancel_failed',
                'message': 'Failed to cancel subscription. Please try again.',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InvoicesView(APIView, StripeConfigCheckMixin):
    """
    List invoices for the organization.
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="List invoices",
        description="Returns a list of invoices for the organization",
        responses={200: InvoiceSerializer(many=True)},
        tags=['Payments']
    )
    def get(self, request):
        """List invoices"""
        org = getattr(request, 'org', None)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # If Stripe not configured, return empty list
        if not StripeService.is_configured():
            return Response({
                'invoices': [],
                'stripe_configured': False,
            })
        
        try:
            invoices = StripeService.list_invoices(org, limit=20)
            return Response({
                'invoices': invoices,
                'stripe_configured': True,
            })
            
        except Exception as e:
            logger.error(f"List invoices error: {e}")
            return Response({
                'invoices': [],
                'error': 'Failed to retrieve invoices',
            })
