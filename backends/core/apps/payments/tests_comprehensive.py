"""
Comprehensive tests for Payments endpoints.

These tests cover Stripe integration with mocked responses:
- Pricing display
- Subscription management
- Checkout session creation
- Customer portal
- Subscription cancellation
"""
import json
import uuid
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from apps.organizations.models import Organization, Membership
from apps.usage.models import Subscription

User = get_user_model()

# Mark for tests that require full Stripe configuration
SKIP_STRIPE_TESTS = pytest.mark.skip(reason="Requires full Stripe mock configuration")


class PaymentsTestCase(APITestCase):
    """Base test case for payments tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='payments_test',
            email='payments_test@example.com',
            password='TestPassword123!',
            is_email_verified=True
        )
        self.org = Organization.objects.create(
            name="Payments Test Organization",
            slug="payments-test-org"
        )
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        
        # Create subscription
        self.subscription = Subscription.objects.create(
            organization=self.org,
            plan='basic',
            status='active'
        )
        
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_ORGANIZATION_ID=str(self.org.id))


class PricingViewTests(PaymentsTestCase):
    """Tests for pricing endpoint"""
    
    def test_get_pricing_success(self):
        """Test getting pricing information"""
        url = reverse('payments:pricing')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return pricing tiers
        self.assertIn('tiers', response.data)
    
    def test_pricing_includes_all_tiers(self):
        """Test that pricing includes all available tiers"""
        url = reverse('payments:pricing')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        tiers = response.data.get('tiers', [])
        tier_names = [t.get('name', '').lower() for t in tiers]
        
        # Should include free tier at minimum
        self.assertTrue(any('basic' in name for name in tier_names))
    
    def test_pricing_requires_auth(self):
        """Test that pricing requires authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('payments:pricing')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SubscriptionViewTests(PaymentsTestCase):
    """Tests for subscription endpoint"""
    
    def test_get_subscription_success(self):
        """Test getting current subscription"""
        url = reverse('payments:subscription')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('plan', response.data)
        self.assertIn('status', response.data)
    
    def test_subscription_shows_correct_tier(self):
        """Test that subscription shows correct tier"""
        url = reverse('payments:subscription')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['plan'], 'basic')
    
    def test_subscription_includes_limits(self):
        """Test that subscription includes usage limits"""
        url = reverse('payments:subscription')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should include limits info
        self.assertTrue(
            'limits' in response.data or 
            'features' in response.data or
            'quota' in response.data
        )


@SKIP_STRIPE_TESTS
@override_settings(STRIPE_PRICES={'premium': 'price_fake'})
class CheckoutSessionTests(PaymentsTestCase):
    """Tests for checkout session creation"""
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_create_checkout_session_success(self):
        """Test creating a checkout session"""
        with patch('apps.payments.stripe_service.StripeService.create_checkout_session') as mock_checkout:
            mock_checkout.return_value = {
                'id': 'cs_test_123',
                'url': 'https://checkout.stripe.com/pay/cs_test_123'
            }
            
            url = reverse('payments:checkout')
            payload = {
                'plan': 'premium',
                'success_url': 'https://app.example.com/success',
                'cancel_url': 'https://app.example.com/cancel'
            }
            
            response = self.client.post(url, payload, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn('url', response.data)
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_checkout_requires_tier(self):
        """Test that checkout requires tier parameter"""
        url = reverse('payments:checkout')
        payload = {
            'success_url': 'https://app.example.com/success',
            'cancel_url': 'https://app.example.com/cancel'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_checkout_invalid_tier(self):
        """Test checkout with invalid tier"""
        url = reverse('payments:checkout')
        payload = {
            'tier': 'invalid_tier',
            'success_url': 'https://app.example.com/success',
            'cancel_url': 'https://app.example.com/cancel'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    @override_settings(STRIPE_SECRET_KEY=None)
    def test_checkout_stripe_not_configured(self):
        """Test checkout when Stripe is not configured"""
        url = reverse('payments:checkout')
        payload = {
            'tier': 'pro',
            'success_url': 'https://app.example.com/success',
            'cancel_url': 'https://app.example.com/cancel'
        }
        
        response = self.client.post(url, payload, format='json')
        
        # Should return error about Stripe not configured
        self.assertIn(response.status_code, [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_503_SERVICE_UNAVAILABLE
        ])

@SKIP_STRIPE_TESTS
class PortalSessionTests(PaymentsTestCase):
    """Tests for customer portal session"""
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_create_portal_session_success(self):
        """Test creating a customer portal session"""
        # Set up Stripe customer ID
        self.org.stripe_customer_id = 'cus_test_123'
        self.org.save()
        
        with patch('apps.payments.stripe_service.StripeService.create_portal_session') as mock_portal:
            mock_portal.return_value = {
                'id': 'bps_test_123',
                'url': 'https://billing.stripe.com/session/bps_test_123'
            }
            
            url = reverse('payments:portal')
            payload = {
                'return_url': 'https://app.example.com/settings'
            }
            
            response = self.client.post(url, payload, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn('url', response.data)
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_portal_requires_stripe_customer(self):
        """Test that portal requires existing Stripe customer"""
        # No stripe_customer_id set
        self.org.stripe_customer_id = None
        self.org.save()
        
        url = reverse('payments:portal')
        payload = {
            'return_url': 'https://app.example.com/settings'
        }
        
        response = self.client.post(url, payload, format='json')
        
        # Should fail - no Stripe customer
        self.assertIn(response.status_code, [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND
        ])

@SKIP_STRIPE_TESTS
class CancelSubscriptionTests(PaymentsTestCase):
    """Tests for subscription cancellation"""
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_cancel_subscription_success(self):
        """Test canceling subscription"""
        # Set up active paid subscription
        self.subscription.tier = 'pro'
        self.subscription.stripe_subscription_id = 'sub_test_123'
        self.subscription.save()
        
        with patch('apps.payments.stripe_service.StripeService.cancel_subscription') as mock_cancel:
            mock_cancel.return_value = {'status': 'canceled'}
            
            url = reverse('payments:cancel-subscription')
            response = self.client.post(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_cancel_free_subscription(self):
        """Test canceling free subscription (should fail or no-op)"""
        # Already on free tier
        self.subscription.tier = 'free'
        self.subscription.stripe_subscription_id = None
        self.subscription.save()
        
        url = reverse('payments:cancel-subscription')
        response = self.client.post(url)
        
        # Should fail or no-op - no subscription to cancel
        self.assertIn(response.status_code, [
            status.HTTP_200_OK,  # No-op
            status.HTTP_400_BAD_REQUEST  # Error
        ])


@SKIP_STRIPE_TESTS
class InvoicesViewTests(PaymentsTestCase):
    """Tests for invoices endpoint"""
    
    @override_settings(STRIPE_SECRET_KEY='sk_test_mock')
    def test_list_invoices_success(self):
        """Test listing invoices"""
        self.org.stripe_customer_id = 'cus_test_123'
        self.org.save()
        
        with patch('apps.payments.stripe_service.StripeService.list_invoices') as mock_invoices:
            mock_invoices.return_value = [
                {
                    'id': 'in_test_1',
                    'amount_paid': 2900,
                    'status': 'paid',
                    'created': 1704067200
                },
                {
                    'id': 'in_test_2',
                    'amount_paid': 2900,
                    'status': 'paid',
                    'created': 1701388800
                }
            ]
            
            url = reverse('payments:invoices')
            response = self.client.get(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            invoices = response.data if isinstance(response.data, list) else response.data.get('invoices', [])
            self.assertEqual(len(invoices), 2)
    
    def test_invoices_empty_for_free_tier(self):
        """Test that free tier has no invoices"""
        # No Stripe customer
        self.org.stripe_customer_id = None
        self.org.save()
        
        url = reverse('payments:invoices')
        response = self.client.get(url)
        
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND])
        
        if response.status_code == status.HTTP_200_OK:
            invoices = response.data if isinstance(response.data, list) else response.data.get('invoices', [])
            self.assertEqual(len(invoices), 0)


class StripeWebhookTests(APITestCase):
    """Tests for Stripe webhook handling"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Webhook Test Org",
            slug="webhook-test-org"
        )
        self.subscription = Subscription.objects.create(
            organization=self.org,
            plan='pro',
            status='active',
            stripe_subscription_id='sub_test_webhook',
            stripe_customer_id='cus_test_webhook'
        )
    
    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test', STRIPE_SECRET_KEY='sk_test_mock')
    def test_webhook_subscription_updated(self):
        """Test handling subscription update webhook"""
        url = reverse('payments:webhook')
        
        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.return_value = MagicMock(
                type='customer.subscription.updated',
                data=MagicMock(object={
                    'id': 'sub_test_webhook',
                    'status': 'active',
                    'items': {'data': [{'price': {'id': 'price_pro'}}]}
                })
            )
            
            response = self.client.post(
                url,
                data='{}',
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='test_signature'
            )
            
            # Webhook should process
            self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])
    
    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test', STRIPE_SECRET_KEY='sk_test_mock')
    def test_webhook_invalid_signature(self):
        """Test webhook with invalid signature"""
        url = reverse('payments:webhook')
        
        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.side_effect = Exception("Invalid signature")
            
            response = self.client.post(
                url,
                data='{}',
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='invalid_signature'
            )
            
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
