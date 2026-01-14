"""
Comprehensive tests for frontend API endpoints
"""
import pytest
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock
from django.utils import timezone
from datetime import timedelta

from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from apps.usage.models import Quota

User = get_user_model()


class FrontendAPITestCase(APITestCase):
    """Base test case for frontend API tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org"
        )
        
        self.membership = Membership.objects.create(
            organization=self.org,
            user=self.user,
            role='admin'
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            status="active"
        )
        
        self.chatbot = Chatbot.objects.create(
            site=self.site,
            name="Test Chatbot",
            description="Test chatbot description",
            status="active",
            config={
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        )
        
        self.quota = Quota.objects.create(
            org_id=self.org.id,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            limits={'max_sites': 10, 'max_chatbots': 25, 'max_pages_per_site': 500},
            usage={'sites_used': 0, 'chat_sessions_used': 0}
        )
        
        # Authenticate user
        self.client.force_authenticate(user=self.user)


class DashboardStatsAPITests(FrontendAPITestCase):
    """Comprehensive tests for dashboard stats API"""
    
    def test_dashboard_stats_success(self):
        """Test successful dashboard stats retrieval"""
        # Create test data
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed", external_job_id=str(uuid.uuid4()),
            documents_indexed=420
        )
        
        ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user=self.user
        )
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check response structure
        data = response.json()
        self.assertIn('sites', data)
        self.assertIn('indexing', data)
        self.assertIn('chatbots', data)
        self.assertIn('chat_sessions', data)
        self.assertIn('usage', data)
        
        # Check sites data
        self.assertEqual(data['sites']['total'], 1)
        self.assertEqual(data['sites']['active'], 1)
        
        # Check indexing data
        self.assertEqual(data['indexing']['total_jobs'], 1)
        self.assertEqual(data['indexing']['completed_jobs'], 1)
        self.assertEqual(data['indexing']['success_rate'], 100.0)
        
        # Check chatbots data
        self.assertEqual(data['chatbots']['total'], 1)
        self.assertEqual(data['chatbots']['active'], 1)
        
        # Check usage data
        self.assertEqual(data['usage']['sites_used'], 1)
        self.assertEqual(data['usage']['sites_limit'], 100)
    
    def test_dashboard_stats_no_organization(self):
        """Test dashboard stats when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertEqual(data['sites']['total'], 0)
        self.assertEqual(data['usage']['sites_used'], 0)
    
    def test_dashboard_stats_with_multiple_sites(self):
        """Test dashboard stats with multiple sites"""
        # Create additional sites
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example2.com",
            status="active"
        )
        
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example3.com",
            status="inactive"
        )
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertEqual(data['sites']['total'], 3)
        self.assertEqual(data['sites']['active'], 2)
    
    def test_dashboard_stats_with_indexing_jobs(self):
        """Test dashboard stats with various indexing jobs"""
        # Create jobs with different statuses
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed", external_job_id=str(uuid.uuid4()),
            documents_indexed=100
        )
        
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="failed", external_job_id=str(uuid.uuid4()),
            error_message="Test error"
        )
        
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="processing", external_job_id=str(uuid.uuid4())
        )
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertEqual(data['indexing']['total_jobs'], 3)
        self.assertEqual(data['indexing']['completed_jobs'], 1)
        self.assertEqual(data['indexing']['failed_jobs'], 1)
        self.assertEqual(data['indexing']['active_jobs'], 1)
        self.assertEqual(data['indexing']['success_rate'], 33.33)
    
    def test_dashboard_stats_with_chat_sessions(self):
        """Test dashboard stats with chat sessions"""
        # Create sessions for last 30 days
        twenty_nine_days_ago = timezone.now() - timedelta(days=29)
        
        s1 = ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user=self.user
        )
        ChatSession.objects.filter(id=s1.id).update(
            created_at=twenty_nine_days_ago,
            closed_at=timezone.now(),
            ended_at=timezone.now(),
            status='ended'
        )
        
        ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user=self.user,
            status="active"
        )
        
        s3 = ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user=self.user
        )
        ChatSession.objects.filter(id=s3.id).update(created_at=timezone.now() - timedelta(days=35))
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertEqual(data['chat_sessions']['total_30_days'], 2)
        self.assertEqual(data['chat_sessions']['active'], 1)
    
    def test_dashboard_stats_usage_tracking(self):
        """Test dashboard stats usage tracking"""
        # Create additional data to test usage
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example2.com",
            status="active"
        )
        
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed", external_job_id=str(uuid.uuid4())
        )
        
        ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user=self.user
        )
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertEqual(data['usage']['sites_used'], 2)
        self.assertEqual(data['usage']['sites_limit'], 100)
        self.assertEqual(data['usage']['indexing_jobs_used'], 1)
        self.assertEqual(data['usage']['indexing_jobs_limit'], 1000)
        self.assertEqual(data['usage']['chat_sessions_used'], 1)
        self.assertEqual(data['usage']['chat_sessions_limit'], 10000)
    
    def test_dashboard_stats_no_quota(self):
        """Test dashboard stats when no quota exists"""
        # Delete quota
        self.quota.delete()
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        # Should use default values when no quota exists
        self.assertEqual(data['usage']['sites_limit'], 100)
        self.assertEqual(data['usage']['indexing_jobs_limit'], 1000)
        self.assertEqual(data['usage']['chat_sessions_limit'], 10000)


class SitesManagementAPITests(FrontendAPITestCase):
    """Comprehensive tests for sites management API"""
    
    def test_sites_list_success(self):
        """Test successful sites list retrieval"""
        url = reverse('sites-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertIn('count', data)
        self.assertIn('results', data)
        self.assertIn('filters', data)
        
        self.assertEqual(data['count'], 1)
        self.assertEqual(len(data['results']), 1)
        
        site_data = data['results'][0]
        self.assertEqual(site_data['domain'], 'https://example.com')
        self.assertEqual(site_data['status'], 'active')
    
    def test_sites_list_with_filters(self):
        """Test sites list with various filters"""
        # Create additional sites
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example2.com",
            status="inactive"
        )
        
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example3.com",
            status="active"
        )
        
        # Test status filter
        url = reverse('sites-management')
        response = self.client.get(url, {'status': 'active'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 2)
        
        # Test search filter
        response = self.client.get(url, {'search': 'example2'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Search is by domain
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['domain'], 'https://example2.com')
    
    def test_sites_list_pagination(self):
        """Test sites list pagination"""
        # Create multiple sites
        for i in range(25):
            Site.objects.create(
                org_id=self.org.id,
                domain=f"https://example{i}.com",
                status="active"
            )
        
        # Test first page
        url = reverse('sites-management')
        response = self.client.get(url, {'page': 1, 'page_size': 10})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 26)  # 25 new + 1 existing
        self.assertEqual(len(data['results']), 10)
        self.assertIsNotNone(data['next'])
        self.assertIsNone(data['previous'])
        
        # Test second page
        response = self.client.get(url, {'page': 2, 'page_size': 10})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['results']), 10)
        self.assertIsNotNone(data['previous'])
    
    def test_sites_list_ordering(self):
        """Test sites list ordering"""
        # Create sites with different creation times
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example1.com",
            status="active"
        )
        
        Site.objects.create(
            org_id=self.org.id,
            domain="https://example2.com",
            status="active"
        )
        
        # Test ordering by domain
        url = reverse('sites-management')
        response = self.client.get(url, {'ordering': 'domain'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        domains = [site['domain'] for site in data['results']]
        self.assertEqual(domains, sorted(domains))
        
        # Test ordering by domain descending
        response = self.client.get(url, {'ordering': '-domain'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        domains = [site['domain'] for site in data['results']]
        self.assertEqual(domains, sorted(domains, reverse=True))
    
    def test_sites_list_no_organization(self):
        """Test sites list when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('sites-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 0)
    
    def test_sites_list_unauthorized(self):
        """Test sites list without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('sites-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_sites_list_with_indexing_jobs(self):
        """Test sites list with indexing jobs data"""
        # Create indexing job for site
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed", external_job_id=str(uuid.uuid4()),
            documents_indexed=100
        )
        
        url = reverse('sites-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        site_data = data['results'][0]
        self.assertEqual(site_data['indexing_jobs_count'], 1)
        self.assertEqual(site_data['active_indexing_jobs'], 0)
        self.assertIsNotNone(site_data['last_indexing_job'])
        self.assertEqual(site_data['last_indexing_job']['status'], 'completed')
    
    def test_sites_list_with_chatbots(self):
        """Test sites list with chatbots data"""
        # Create additional chatbot
        Chatbot.objects.create(
            site=self.site,
            name="Test Chatbot 2"
        )
        
        url = reverse('sites-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        site_data = data['results'][0]
        self.assertEqual(site_data['chatbots_count'], 2)
    
    def test_sites_list_error_handling(self):
        """Test sites list error handling"""
        # Create multiple sites to test capping
        for i in range(25):
            Site.objects.create(
                org_id=self.org.id,
                domain=f"https://error-test-{i}.com",
                status="active"
            )
        
        # Test with invalid page size
        url = reverse('sites-management')
        response = self.client.get(url, {'page_size': 1000})  # Exceeds max
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['results']), 26)  # Should return all created (cap is 100)


class SitesCreateAPITests(FrontendAPITestCase):
    """Comprehensive tests for site creation API"""
    
    def test_create_site_success(self):
        """Test successful site creation"""
        url = reverse('create-site')
        data = {
            'domain': 'https://newsite.com'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        response_data = response.json()
        self.assertIn('id', response_data)
        self.assertEqual(response_data['domain'], 'https://newsite.com')
        self.assertEqual(response_data['status'], 'active')
        
        # Verify site was created in database
        site = Site.objects.get(domain='https://newsite.com')
        self.assertEqual(site.org_id, self.org.id)
    
    def test_create_site_domain_validation(self):
        """Test site creation with domain validation"""
        url = reverse('create-site')
        
        # Test invalid domain
        data = {
            'domain': 'not-a-url'
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('domain', response.json())
        
        # Test missing protocol
        data = {
            'domain': 'valid-example.com'
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should automatically add https://
        self.assertEqual(response.json()['domain'], 'https://valid-example.com')
    
    def test_create_site_quota_exceeded(self):
        """Test site creation when quota is exceeded"""
        # Set quota limit to 1
        self.quota.limits['max_sites'] = 1
        self.quota.save()
        
        url = reverse('create-site')
        data = {
            'domain': 'https://newsite.com'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())
        self.assertIn('limit reached', response.json()['error'].lower())
    
    def test_create_site_no_organization(self):
        """Test site creation when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('create-site')
        data = {
            'domain': 'https://newsite.com'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())
    
    def test_create_site_unauthorized(self):
        """Test site creation without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('create-site')
        data = {
            'domain': 'https://newsite.com'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_create_site_missing_required_fields(self):
        """Test site creation with missing required fields"""
        url = reverse('create-site')
        
        # Test missing domain
        data = {}
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('domain', response.json())
    
    def test_create_site_duplicate_domain(self):
        """Test site creation with duplicate domain for DIFFERENT org should succeed"""
        # Create another organization and membership
        other_org = Organization.objects.create(name="Other Org", slug="other-org")
        Membership.objects.create(organization=other_org, user=self.user, role='admin')
        
        url = reverse('create-site')
        data = {
            'domain': 'https://example.com'  # Already exists for self.org, but not for other_org
        }
        
        # Pass other_org.id to ensure we use the new organization context
        response = self.client.post(f"{url}?org_id={other_org.id}", data, format='json')
        # If it succeeds, it's because it's a new org context.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_create_site_error_handling(self):
        """Test site creation error handling"""
        url = reverse('create-site')
        
        # Test with invalid JSON
        response = self.client.post(
            url,
            'invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
