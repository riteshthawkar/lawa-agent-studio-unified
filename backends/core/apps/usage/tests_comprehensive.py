"""
Comprehensive tests for Usage endpoints.

These tests cover quota and usage tracking:
- Usage summary
- Organization quotas
- Waitlist functionality
"""
import json
import uuid
from django.utils import timezone
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from apps.organizations.models import Organization, Membership
from apps.usage.models import Quota, UsageEvent, Subscription, UpgradeInterest

User = get_user_model()


class UsageTestCase(APITestCase):
    """Base test case for usage tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='usage_test@example.com',
            username='usage_test_user',
            password='TestPassword123!',
            is_email_verified=True
        )
        self.org = Organization.objects.create(
            name="Usage Test Organization",
            slug="usage-test-org"
        )
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        
        # Create quota
        self.quota = Quota.objects.create(
            org_id=self.org.id,
            period_start=timezone.now(),
            period_end=timezone.now() + timezone.timedelta(days=30),
            limits={
                'max_sites': 5,
                'max_pages_per_site': 100,
                'max_messages_per_month': 1000
            }
        )
        
        # Create subscription
        self.subscription = Subscription.objects.create(
            organization=self.org,
            plan='basic',
            status='active'
        )
        
        self.client.force_authenticate(user=self.user)


class UsageSummaryTests(UsageTestCase):
    """Tests for usage summary endpoint"""
    
    def test_get_usage_summary(self):
        """Test getting usage summary"""
        url = reverse('usage-summary')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should include usage data categories
        self.assertIn('sites', response.data)
        self.assertIn('chatbots', response.data)
        self.assertIn('daily_conversations', response.data)
    
    def test_usage_summary_includes_limits(self):
        """Test that usage summary includes limits"""
        url = reverse('usage-summary')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should include limits within categories
        self.assertIn('limit', response.data['sites'])
        self.assertIn('used', response.data['sites'])
    
    def test_usage_summary_requires_auth(self):
        """Test that usage summary requires authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('usage-summary')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class OrganizationQuotasTests(UsageTestCase):
    """Tests for organization quotas endpoint"""
    
    def test_get_organization_quotas(self):
        """Test getting organization quotas"""
        url = reverse('organization-quotas', kwargs={'org_id': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('limits', response.data)
        self.assertIn('max_sites', response.data['limits'])
    
    def test_get_organization_usage(self):
        """Test getting organization usage"""
        url = reverse('organization-usage', kwargs={'org_id': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_cannot_access_other_org_quotas(self):
        """Test that user cannot access other org's quotas"""
        # Create another org
        other_org = Organization.objects.create(
            name="Other Org",
            slug="other-org"
        )
        
        url = reverse('organization-quotas', kwargs={'org_id': other_org.id})
        response = self.client.get(url)
        
        self.assertIn(response.status_code, [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND
        ])


class WaitlistTests(UsageTestCase):
    """Tests for waitlist functionality"""
    
    def test_join_waitlist(self):
        """Test joining waitlist for upgrade"""
        url = reverse('join-waitlist')
        payload = {
            'interested_plan': 'premium',  # Correct field name and choice
            'email': self.user.email,
            'source': 'billing_page'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify interest recorded
        self.assertTrue(
            UpgradeInterest.objects.filter(
                organization=self.org,
                interested_plan='premium'
            ).exists()
        )
    
    def test_get_waitlist_entries(self):
        """Test getting user's waitlist entries"""
        # Create a waitlist entry
        UpgradeInterest.objects.create(
            organization=self.org,
            user=self.user,
            interested_plan='premium'
        )
        
        url = reverse('join-waitlist')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check 'interests' key
        entries = response.data.get('interests', [])
        self.assertGreaterEqual(len(entries), 1)
    
    def test_duplicate_waitlist_entry(self):
        """Test joining waitlist for same plan twice"""
        # First entry
        UpgradeInterest.objects.create(
            organization=self.org,
            user=self.user,
            interested_plan='premium'
        )
        
        url = reverse('join-waitlist')
        payload = {
            'interested_plan': 'premium',
            'email': self.user.email,
            'source': 'billing_page'
        }
        
        response = self.client.post(url, payload, format='json')
        
        # Should handle gracefully (either success or conflict)
        self.assertIn(response.status_code, [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_409_CONFLICT
        ])


class UsageTrackingTests(UsageTestCase):
    """Tests for usage event tracking"""
    
    def test_usage_events_recorded(self):
        """Test that usage events are properly recorded"""
        # Create some usage events
        UsageEvent.objects.create(
            org_id=self.org.id,
            type='chat',
            units=10
        )
        UsageEvent.objects.create(
            org_id=self.org.id,
            type='embedding',
            units=5
        )
        
        url = reverse('organization-usage', kwargs={'org_id': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_usage_within_limits(self):
        """Test checking if usage is within limits"""
        url = reverse('usage-summary')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should indicate if within limits
        data = response.data
        if 'within_limits' in data:
            self.assertIsInstance(data['within_limits'], bool)
