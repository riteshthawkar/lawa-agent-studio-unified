from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from unittest.mock import patch

User = get_user_model()


class SiteAPITestCase(APITestCase):
    """Test site API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123'
        )
        
        self.org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        
        self.membership = Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain='https://example.com',
            verification_method='dns',
            status='pending'
        )
        
        # Authenticate
        self.client.force_authenticate(user=self.user)
        self.client.defaults['HTTP_X_ORG_ID'] = str(self.org.id)
    
    def test_site_creation(self):
        """Test site creation endpoint"""
        url = reverse('site-list')
        data = {
            'domain': 'https://newsite.com',
            'verification_method': 'file'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['domain'], 'https://newsite.com')
        self.assertEqual(response.data['verification_method'], 'file')
        
        # Check site was created
        self.assertTrue(Site.objects.filter(domain='https://newsite.com').exists())
    
    def test_site_list(self):
        """Test site list endpoint"""
        url = reverse('site-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_site_detail(self):
        """Test site detail endpoint"""
        url = reverse('site-detail', kwargs={'pk': self.site.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['domain'], 'https://example.com')
    
    @patch('apps.sites.services.SiteVerificationService.verify_site')
    def test_site_verification_success(self, mock_verify):
        """Test successful site verification"""
        mock_verify.return_value = True
        
        url = reverse('verify-site', kwargs={'site_id': self.site.id})
        data = {
            'verification_token': self.site.verification_token
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Site verified successfully', response.data['message'])
        
        # Check site was marked as verified
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, 'active')
        self.assertIsNotNone(self.site.verified_at)
    
    @patch('apps.sites.services.SiteVerificationService.verify_site')
    def test_site_verification_failure(self, mock_verify):
        """Test failed site verification"""
        mock_verify.return_value = False
        
        url = reverse('verify-site', kwargs={'site_id': self.site.id})
        data = {
            'verification_token': self.site.verification_token
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('verification failed', response.data['error'].lower())
    
    def test_verification_instructions(self):
        """Test verification instructions endpoint"""
        url = reverse('site-verification-instructions', kwargs={'site_id': self.site.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('instructions', response.data)
        self.assertIn('verification_token', response.data)
    
    def test_site_update(self):
        """Test site update endpoint"""
        url = reverse('site-detail', kwargs={'pk': self.site.id})
        data = {
            'domain': 'https://updated-example.com'
        }
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['domain'], 'https://updated-example.com')
    
    def test_site_deletion(self):
        """Test site deletion endpoint"""
        url = reverse('site-detail', kwargs={'pk': self.site.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Site.objects.filter(id=self.site.id).exists())


class SiteVerificationServiceTestCase(TestCase):
    """Test site verification service"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain='https://example.com',
            verification_method='dns',
            status='pending'
        )
    
    @patch('dns.resolver.resolve')
    def test_dns_verification_success(self, mock_resolve):
        """Test successful DNS verification"""
        from apps.sites.services import SiteVerificationService
        
        # Mock DNS response
        mock_record = type('MockRecord', (), {'__str__': lambda x: f'"{self.site.verification_token}"'})()
        mock_resolve.return_value = [mock_record]
        
        service = SiteVerificationService()
        result = service.verify_dns_record(self.site)
        
        self.assertTrue(result)
        mock_resolve.assert_called_once_with(f'_lawa-verification.example.com', 'TXT')
    
    @patch('dns.resolver.resolve')
    def test_dns_verification_failure(self, mock_resolve):
        """Test failed DNS verification"""
        from apps.sites.services import SiteVerificationService
        
        # Mock DNS response with wrong token
        mock_record = type('MockRecord', (), {'__str__': lambda x: '"wrong-token"'})()
        mock_resolve.return_value = [mock_record]
        
        service = SiteVerificationService()
        result = service.verify_dns_record(self.site)
        
        self.assertFalse(result)
    
    @patch('requests.get')
    def test_file_verification_success(self, mock_get):
        """Test successful file verification"""
        from apps.sites.services import SiteVerificationService
        
        # Mock HTTP response
        mock_response = type('MockResponse', (), {
            'text': self.site.verification_token,
            'raise_for_status': lambda: None
        })()
        mock_get.return_value = mock_response
        
        service = SiteVerificationService()
        result = service.verify_file_upload(self.site)
        
        self.assertTrue(result)
        expected_url = f"https://example.com/lawa-verification-{self.site.verification_token}.txt"
        mock_get.assert_called_once_with(expected_url, timeout=30)
    
    @patch('requests.get')
    def test_file_verification_failure(self, mock_get):
        """Test failed file verification"""
        from apps.sites.services import SiteVerificationService
        
        # Mock HTTP response with wrong content
        mock_response = type('MockResponse', (), {
            'text': 'wrong-content',
            'raise_for_status': lambda: None
        })()
        mock_get.return_value = mock_response
        
        service = SiteVerificationService()
        result = service.verify_file_upload(self.site)
        
        self.assertFalse(result)
