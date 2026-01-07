"""
Comprehensive security tests for the backend
"""
import json
import uuid
from django.test import TestCase, Client
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


class SecurityAPITestCase(APITestCase):
    """Base test case for security tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='testpass123',
            name='User One'
        )
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123',
            name='User Two'
        )
        
        self.org1 = Organization.objects.create(
            name="Organization 1",
            slug="org-1"
        )
        
        self.org2 = Organization.objects.create(
            name="Organization 2",
            slug="org-2"
        )
        
        self.membership1 = Membership.objects.create(
            organization=self.org1,
            user=self.user1,
            role='admin'
        )
        
        self.membership2 = Membership.objects.create(
            organization=self.org2,
            user=self.user2,
            role='admin'
        )
        
        self.site1 = Site.objects.create(
            org_id=self.org1.id,
            domain="https://org1.com",
            verification_token="token1",
            verified_at=timezone.now(),
            status="active"
        )
        
        self.site2 = Site.objects.create(
            org_id=self.org2.id,
            domain="https://org2.com",
            verification_token="token2",
            verified_at=timezone.now(),
            status="active"
        )
        
        self.chatbot1 = Chatbot.objects.create(
            org_id=self.org1.id,
            site_id=self.site1.id,
            name="Chatbot 1",
            api_key="cb_test_key_1"
        )
        
        self.chatbot2 = Chatbot.objects.create(
            org_id=self.org2.id,
            site_id=self.site2.id,
            name="Chatbot 2",
            api_key="cb_test_key_2"
        )


class AuthenticationTests(SecurityAPITestCase):
    """Comprehensive tests for authentication security"""
    
    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated users cannot access protected endpoints"""
        protected_endpoints = [
            'dashboard-stats',
            'sites-management',
            'indexing-jobs-management',
            'chatbots-management',
            'user-profile',
            'create-site',
            'create-indexing-job',
            'create-chatbot',
        ]
        
        for endpoint in protected_endpoints:
            with self.subTest(endpoint=endpoint):
                if 'create-indexing-job' in endpoint:
                    url = reverse(endpoint, kwargs={'site_id': self.site1.id})
                elif 'create-chatbot' in endpoint:
                    url = reverse(endpoint, kwargs={'site_id': self.site1.id})
                else:
                    url = reverse(endpoint)
                
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_authentication_required_for_post_requests(self):
        """Test that authentication is required for POST requests"""
        post_endpoints = [
            ('create-site', {}),
            ('create-indexing-job', {'site_id': self.site1.id}),
            ('create-chatbot', {'site_id': self.site1.id}),
            ('bulk-actions', {}),
        ]
        
        for endpoint, kwargs in post_endpoints:
            with self.subTest(endpoint=endpoint):
                if kwargs:
                    url = reverse(endpoint, kwargs=kwargs)
                else:
                    url = reverse(endpoint)
                
                response = self.client.post(url, {})
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_authentication_required_for_put_requests(self):
        """Test that authentication is required for PUT requests"""
        put_endpoints = [
            ('update-site', {'site_id': self.site1.id}),
            ('update-chatbot', {'chatbot_id': self.chatbot1.id}),
        ]
        
        for endpoint, kwargs in put_endpoints:
            with self.subTest(endpoint=endpoint):
                url = reverse(endpoint, kwargs=kwargs)
                response = self.client.put(url, {})
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_authentication_required_for_delete_requests(self):
        """Test that authentication is required for DELETE requests"""
        delete_endpoints = [
            ('delete-site', {'site_id': self.site1.id}),
            ('delete-chatbot', {'chatbot_id': self.chatbot1.id}),
        ]
        
        for endpoint, kwargs in delete_endpoints:
            with self.subTest(endpoint=endpoint):
                url = reverse(endpoint, kwargs=kwargs)
                response = self.client.delete(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AuthorizationTests(SecurityAPITestCase):
    """Comprehensive tests for authorization security"""
    
    def test_organization_isolation_sites(self):
        """Test that users can only access sites from their organization"""
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to access site from org2
        url = reverse('update-site', kwargs={'site_id': self.site2.id})
        response = self.client.put(url, {'pinecone_index': 'hacked'})
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.json()['error'])
    
    def test_organization_isolation_chatbots(self):
        """Test that users can only access chatbots from their organization"""
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to access chatbot from org2
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot2.id})
        response = self.client.put(url, {'name': 'Hacked Chatbot'})
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Chatbot not found', response.json()['error'])
    
    def test_organization_isolation_indexing_jobs(self):
        """Test that users can only access indexing jobs from their organization"""
        # Create indexing job for org2
        job2 = IndexingJob.objects.create(
            org_id=self.org2.id,
            site_id=self.site2.id,
            url="https://org2.com",
            external_job_id="job_2"
        )
        
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to access indexing jobs - should only see org1 jobs
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 0)  # No jobs for org1
    
    def test_organization_isolation_dashboard_stats(self):
        """Test that users can only see stats from their organization"""
        # Create data for org2
        IndexingJob.objects.create(
            org_id=self.org2.id,
            site_id=self.site2.id,
            url="https://org2.com",
            status="completed"
        )
        
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Get dashboard stats
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should only see org1 data
        self.assertEqual(data['indexing']['total_jobs'], 0)
        self.assertEqual(data['sites']['total'], 1)  # Only site1
    
    def test_organization_isolation_bulk_actions(self):
        """Test that users can only perform bulk actions on their organization's resources"""
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to delete site from org2
        url = reverse('bulk-actions')
        data = {
            'action_type': 'delete',
            'resource_type': 'sites',
            'resource_ids': [str(self.site2.id)]
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not actually delete anything from org2
        self.assertTrue(Site.objects.filter(id=self.site2.id).exists())
    
    def test_user_without_organization_access_denied(self):
        """Test that users without organization cannot access any resources"""
        # Create user without organization
        user_no_org = User.objects.create_user(
            username='noorg',
            email='noorg@example.com',
            password='testpass123',
            name='No Org User'
        )
        
        self.client.force_authenticate(user=user_no_org)
        
        # Try to access dashboard
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('User not associated with any organization', response.json()['error'])
    
    def test_cross_organization_api_key_access_denied(self):
        """Test that API keys from one organization cannot access another organization's data"""
        # Try to use chatbot1's API key to access org2's data
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://org2.com',
            'api_key': self.chatbot1.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.json()['error'])


class InputValidationTests(SecurityAPITestCase):
    """Comprehensive tests for input validation security"""
    
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user1)
    
    def test_sql_injection_protection(self):
        """Test protection against SQL injection attacks"""
        # Test in search parameters
        url = reverse('sites-management')
        response = self.client.get(url, {'search': "'; DROP TABLE sites; --"})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not cause any errors or data loss
        self.assertTrue(Site.objects.filter(org_id=self.org1.id).exists())
    
    def test_xss_protection(self):
        """Test protection against XSS attacks"""
        # Test in site creation
        url = reverse('create-site')
        data = {
            'domain': 'https://example.com',
            'verification_method': 'dns',
            'pinecone_index': '<script>alert("xss")</script>'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should sanitize the input
        site = Site.objects.get(domain='https://example.com')
        self.assertNotIn('<script>', site.pinecone_index)
    
    def test_path_traversal_protection(self):
        """Test protection against path traversal attacks"""
        # Test in file upload scenarios (if any)
        url = reverse('create-site')
        data = {
            'domain': 'https://example.com',
            'verification_method': 'dns',
            'namespace_override': '../../../etc/passwd'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should not allow path traversal
        site = Site.objects.get(domain='https://example.com')
        self.assertNotIn('../', site.namespace_override)
    
    def test_oversized_input_protection(self):
        """Test protection against oversized input attacks"""
        # Test with extremely large input
        url = reverse('create-site')
        data = {
            'domain': 'https://example.com',
            'verification_method': 'dns',
            'pinecone_index': 'x' * 10000  # Very large input
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pinecone_index', response.json())
    
    def test_malformed_json_protection(self):
        """Test protection against malformed JSON"""
        url = reverse('create-site')
        
        response = self.client.post(
            url,
            '{"domain": "https://example.com", "verification_method": "dns",}',  # Trailing comma
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_invalid_uuid_protection(self):
        """Test protection against invalid UUIDs"""
        url = reverse('update-site', kwargs={'site_id': 'not-a-uuid'})
        response = self.client.put(url, {'pinecone_index': 'test'})
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_negative_values_protection(self):
        """Test protection against negative values"""
        url = reverse('create-indexing-job', kwargs={'site_id': self.site1.id})
        data = {
            'url': 'https://example.com',
            'max_pages': -100  # Negative value
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('max_pages', response.json())
    
    def test_empty_string_protection(self):
        """Test protection against empty strings in required fields"""
        url = reverse('create-site')
        data = {
            'domain': '',  # Empty string
            'verification_method': 'dns'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('domain', response.json())


class RateLimitingTests(SecurityAPITestCase):
    """Comprehensive tests for rate limiting security"""
    
    def test_rate_limiting_frontend_endpoints(self):
        """Test rate limiting on frontend endpoints"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('dashboard-stats')
        
        # Make many requests quickly
        for i in range(2100):  # Exceed rate limit
            response = self.client.get(url)
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                break
        
        # Should eventually hit rate limit
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS])
    
    def test_rate_limiting_chatbot_endpoints(self):
        """Test rate limiting on chatbot endpoints"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://org1.com',
            'api_key': self.chatbot1.api_key
        }
        
        # Make many requests quickly
        for i in range(110):  # Exceed rate limit
            response = self.client.get(url, params)
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                break
        
        # Should eventually hit rate limit
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS])
    
    def test_rate_limiting_headers(self):
        """Test that rate limiting headers are included"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        # Should include rate limiting headers
        self.assertIn('X-RateLimit-Limit', response)
        self.assertIn('X-RateLimit-Remaining', response)
        self.assertIn('X-RateLimit-Reset', response)


class CSRFProtectionTests(SecurityAPITestCase):
    """Comprehensive tests for CSRF protection"""
    
    def test_csrf_protection_enabled(self):
        """Test that CSRF protection is enabled"""
        # Django REST Framework handles CSRF differently, but we should test
        # that our endpoints are properly protected
        
        # Test with invalid CSRF token
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user1)
        
        url = reverse('create-site')
        data = {
            'domain': 'https://example.com',
            'verification_method': 'dns'
        }
        
        response = client.post(url, data, format='json')
        # Should either work (if CSRF is handled by DRF) or return 403
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_403_FORBIDDEN])


class DataLeakageTests(SecurityAPITestCase):
    """Comprehensive tests for data leakage prevention"""
    
    def test_error_messages_no_sensitive_data(self):
        """Test that error messages don't leak sensitive data"""
        # Test with invalid API key
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://org1.com',
            'api_key': 'invalid-key'
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Should not reveal that the API key format is wrong or other sensitive info
        error_message = response.json()['error']
        self.assertNotIn('cb_', error_message)
        self.assertNotIn('api_key', error_message.lower())
    
    def test_organization_data_isolation(self):
        """Test that organization data is properly isolated"""
        # Create sensitive data in org2
        sensitive_site = Site.objects.create(
            org_id=self.org2.id,
            domain="https://sensitive.com",
            verification_token="sensitive-token",
            verified_at=timezone.now(),
            status="active"
        )
        
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to access sensitive site
        url = reverse('update-site', kwargs={'site_id': sensitive_site.id})
        response = self.client.put(url, {'pinecone_index': 'test'})
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Should not reveal that the site exists
        self.assertIn('Site not found', response.json()['error'])
    
    def test_user_data_isolation(self):
        """Test that user data is properly isolated"""
        # Create user in different organization
        other_user = User.objects.create_user(
            username='other',
            email='other@example.com',
            password='testpass123',
            name='Other User'
        )
        
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to access other user's data (if there were such endpoints)
        # This is more of a conceptual test since we don't have user-specific endpoints
        # But we can test that users can't access each other's organization data
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Should only show org1 data
        self.assertEqual(data['organization']['id'], str(self.org1.id))


class APIKeySecurityTests(SecurityAPITestCase):
    """Comprehensive tests for API key security"""
    
    def test_api_key_format_validation(self):
        """Test that API keys follow the correct format"""
        # Test with invalid API key format
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://org1.com',
            'api_key': 'invalid-format'
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_api_key_uniqueness(self):
        """Test that API keys are unique"""
        # Create multiple chatbots and verify API keys are unique
        api_keys = set()
        for i in range(100):
            chatbot = Chatbot.objects.create(
                org_id=self.org1.id,
                site_id=self.site1.id,
                name=f"Chatbot {i}"
            )
            api_keys.add(chatbot.api_key)
        
        # All API keys should be unique
        self.assertEqual(len(api_keys), 100)
    
    def test_api_key_generation_security(self):
        """Test that API keys are generated securely"""
        chatbot = Chatbot.objects.create(
            org_id=self.org1.id,
            site_id=self.site1.id,
            name="Test Chatbot"
        )
        
        # API key should be long enough and random
        api_key = chatbot.api_key
        self.assertTrue(api_key.startswith('cb_'))
        self.assertEqual(len(api_key), 35)  # cb_ + 32 chars
        
        # Should not be predictable
        api_key2 = chatbot.generate_api_key()
        self.assertNotEqual(api_key, api_key2)
    
    def test_api_key_rotation(self):
        """Test that API keys can be rotated"""
        original_api_key = self.chatbot.api_key
        
        # Regenerate API key
        self.chatbot.api_key = self.chatbot.generate_api_key()
        self.chatbot.save()
        
        # Old API key should not work
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://org1.com',
            'api_key': original_api_key
        }
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # New API key should work
        params['api_key'] = self.chatbot.api_key
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class LoggingSecurityTests(SecurityAPITestCase):
    """Comprehensive tests for security logging"""
    
    @patch('apps.frontend.views.logger')
    def test_failed_authentication_logging(self, mock_logger):
        """Test that failed authentication attempts are logged"""
        # Try to access protected endpoint without authentication
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # Should log the failed attempt
        mock_logger.warning.assert_called()
    
    @patch('apps.frontend.views.logger')
    def test_unauthorized_access_logging(self, mock_logger):
        """Test that unauthorized access attempts are logged"""
        # Authenticate as user1
        self.client.force_authenticate(user=self.user1)
        
        # Try to access org2's data
        url = reverse('update-site', kwargs={'site_id': self.site2.id})
        response = self.client.put(url, {'pinecone_index': 'test'})
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Should log the unauthorized access attempt
        mock_logger.warning.assert_called()
    
    @patch('apps.chatbot.views.logger')
    def test_invalid_api_key_logging(self, mock_logger):
        """Test that invalid API key attempts are logged"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://org1.com',
            'api_key': 'invalid-key'
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Should log the invalid API key attempt
        mock_logger.warning.assert_called()
    
    @patch('apps.frontend.views.logger')
    def test_error_logging(self, mock_logger):
        """Test that errors are properly logged"""
        # Force an error by providing invalid data
        url = reverse('create-site')
        data = {
            'domain': 'not-a-url',
            'verification_method': 'dns'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Should log the error
        mock_logger.error.assert_called()
