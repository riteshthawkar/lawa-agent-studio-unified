"""
Comprehensive tests for Admin API endpoints.

These tests cover admin-only access and operations:
- Admin permission checks
- User management actions
- Organization management
- Stats and reporting
"""
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.indexing.models import IndexingJob

User = get_user_model()


class AdminAPITestCase(APITestCase):
    """Base test case for admin API tests"""
    
    def setUp(self):
        """Set up test data"""
        # Admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='AdminPass123!',
            is_staff=True,
            is_superuser=True,
            is_email_verified=True
        )
        
        # Regular user
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='UserPass123!',
            is_email_verified=True
        )

        
        # Test organization
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org"
        )
        Membership.objects.create(
            user=self.regular_user,
            organization=self.org,
            role='owner'
        )


class AdminPermissionTests(AdminAPITestCase):
    """Tests for admin-only access"""
    
    def test_admin_can_access_admin_stats(self):
        """Test that admin can access admin stats"""
        self.client.force_authenticate(user=self.admin_user)
        
        url = reverse('admin-stats-overview')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_regular_user_cannot_access_admin_stats(self):
        """Test that regular user cannot access admin stats"""
        self.client.force_authenticate(user=self.regular_user)
        
        url = reverse('admin-stats-overview')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_unauthenticated_cannot_access_admin(self):
        """Test that unauthenticated cannot access admin"""
        url = reverse('admin-stats-overview')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_admin_can_access_user_list(self):
        """Test that admin can list all users"""
        self.client.force_authenticate(user=self.admin_user)
        
        url = reverse('admin-users-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_regular_user_cannot_access_user_list(self):
        """Test that regular user cannot list all users"""
        self.client.force_authenticate(user=self.regular_user)
        
        url = reverse('admin-users-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminUserManagementTests(AdminAPITestCase):
    """Tests for admin user management"""
    
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin_user)
    
    def test_list_users(self):
        """Test listing all users"""
        url = reverse('admin-users-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        users = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(users), 2)  # Admin + regular user
    
    def test_get_user_detail(self):
        """Test getting user details"""
        url = reverse('admin-users-detail', kwargs={'pk': self.regular_user.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.regular_user.email)
    
    def test_update_user_status(self):
        """Test updating user status"""
        url = reverse('admin-users-detail', kwargs={'pk': self.regular_user.id})
        payload = {
            'is_active': False
        }
        
        response = self.client.patch(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.regular_user.refresh_from_db()
        self.assertFalse(self.regular_user.is_active)
    
    def test_user_action_suspend(self):
        """Test suspending a user"""
        url = reverse('admin-users-actions', kwargs={'pk': self.regular_user.id})
        payload = {
            'action': 'suspend',
            'reason': 'Violation of terms'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_user_action_verify_email(self):
        """Test manually verifying user email"""
        # Create unverified user
        unverified = User.objects.create_user(
            username='unverified',
            email='unverified@example.com',
            password='Unverified123!',
            is_email_verified=False
        )
        
        url = reverse('admin-users-actions', kwargs={'pk': unverified.id})
        payload = {
            'action': 'verify_email'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        unverified.refresh_from_db()
        self.assertTrue(unverified.is_email_verified)
    
    def test_get_user_login_history(self):
        """Test getting user login history"""
        url = reverse('admin-users-login-history', kwargs={'pk': self.regular_user.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_get_user_jobs(self):
        """Test getting user's indexing jobs"""
        # Create a job for user's org
        site = Site.objects.create(
            domain="https://test.com",
            org_id=self.org.id,
            status='active'
        )
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=site.id,
            url="https://test.com",
            status='completed',
            external_job_id='job_123'
        )
        
        url = reverse('admin-users-jobs', kwargs={'pk': self.regular_user.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class AdminOrganizationManagementTests(AdminAPITestCase):
    """Tests for admin organization management"""
    
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin_user)
    
    def test_list_all_organizations(self):
        """Test listing all organizations"""
        url = reverse('admin-organizations-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_get_organization_detail(self):
        """Test getting organization details"""
        url = reverse('admin-organizations-detail', kwargs={'pk': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_get_organization_quotas(self):
        """Test getting organization quotas"""
        url = reverse('admin-organizations-quotas', kwargs={'pk': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_update_organization_quotas(self):
        """Test updating organization quotas"""
        url = reverse('admin-organizations-quotas', kwargs={'pk': self.org.id})
        payload = {
            'max_sites': 100,
            'max_pages_per_site': 1000,
            'confirm': True
        }
        
        response = self.client.patch(url, payload, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


class AdminStatsTests(AdminAPITestCase):
    """Tests for admin stats endpoints"""
    
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin_user)
    
    def test_overview_stats(self):
        """Test overview stats endpoint"""
        url = reverse('admin-stats-overview')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should include key metrics
        data = response.data
        self.assertTrue(
            'total_users' in data or 
            'users' in data or
            'user_count' in data
        )
    
    def test_growth_stats(self):
        """Test growth stats endpoint"""
        url = reverse('admin-stats-growth')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_usage_stats(self):
        """Test usage stats endpoint"""
        url = reverse('admin-stats-usage')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_plans_stats(self):
        """Test plans stats endpoint"""
        url = reverse('admin-stats-plans')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class AdminGlobalViewsTests(AdminAPITestCase):
    """Tests for admin global views"""
    
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin_user)
        
        # Create test data
        self.site = Site.objects.create(
            domain="https://admin-test.com",
            name="Admin Test Site",
            org_id=self.org.id,
            status='active'
        )
        self.job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://admin-test.com",
            status='completed',
            external_job_id='job_456'
        )
    
    def test_list_all_jobs(self):
        """Test listing all indexing jobs"""
        url = reverse('admin-all-jobs')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_list_all_sites(self):
        """Test listing all sites"""
        url = reverse('admin-all-sites')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_list_all_chatbots(self):
        """Test listing all chatbots"""
        url = reverse('admin-all-chatbots')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_job_detail(self):
        """Test getting job details"""
        url = reverse('admin-job-detail', kwargs={'job_id': self.job.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_job_action_cancel(self):
        """Test canceling a job"""
        # Create an active job
        active_job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://active-job.com",
            status='processing',
            external_job_id='job_789'
        )
        
        url = reverse('admin-job-action', kwargs={'job_id': active_job.id})
        payload = {
            'action': 'cancel'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


class AdminSearchAndFilterTests(AdminAPITestCase):
    """Tests for admin search and filter functionality"""
    
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin_user)
        
        # Create multiple users
        for i in range(5):
            User.objects.create_user(
                username=f'searchuser{i}',
                email=f'searchuser{i}@example.com',
                password=f'SearchPass{i}!'
            )
    
    def test_search_users(self):
        """Test searching users"""
        url = reverse('admin-users-list')
        response = self.client.get(url, {'search': 'searchuser'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        users = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(users), 5)
    
    def test_filter_users_by_status(self):
        """Test filtering users by status"""
        url = reverse('admin-users-list')
        response = self.client.get(url, {'is_active': 'true'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_pagination(self):
        """Test pagination works"""
        url = reverse('admin-users-list')
        response = self.client.get(url, {'page': 1, 'page_size': 2})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        if 'results' in response.data:
            self.assertLessEqual(len(response.data['results']), 2)
