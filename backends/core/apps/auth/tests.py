from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.auth.models import APIKey
import json

User = get_user_model()


class AuthAPITestCase(APITestCase):
    """Test authentication API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.user_data = {
            'email': 'test@example.com',
            'username': 'testuser',
            'name': 'Test User',
            'password': 'testpass123',
            'password_confirm': 'testpass123'
        }
        
        self.login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
    
    def test_user_registration(self):
        """Test user registration endpoint"""
        url = reverse('user-signup')
        response = self.client.post(url, self.user_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('user', response.data)
        # Tokens not returned until email verified
        self.assertIn('message', response.data)
        # Organization is created but not returned in response
        # self.assertIn('organization', response.data)
        
        # Check user was created
        user = User.objects.get(email='test@example.com')
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.name, 'Test User')
        
        # Check organization was created
        self.assertTrue(Organization.objects.filter(memberships__user=user).exists())
    
    def test_user_login(self):
        """Test user login endpoint"""
        # Create user first
        user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123',
            is_email_verified=True
        )
        
        # Create organization and membership
        org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        Membership.objects.create(user=user, organization=org, role='owner')
        
        url = reverse('user-login')
        response = self.client.post(url, self.login_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)
        self.assertIn('tokens', response.data)
        self.assertIn('organization', response.data)
    
    def test_user_profile(self):
        """Test user profile endpoint"""
        # Create user and organization
        user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123'
        )
        
        org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        Membership.objects.create(user=user, organization=org, role='owner')
        
        # Authenticate
        self.client.force_authenticate(user=user)
        
        url = reverse('user-profile')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('organization', response.data)
        self.assertEqual(response.data['organization']['slug'], 'test-org')
    
    def test_api_key_creation(self):
        """Test API key creation"""
        # Create user and organization
        user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123',
            is_email_verified=True
        )
        
        org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        Membership.objects.create(user=user, organization=org, role='owner')
        
        # Authenticate
        self.client.force_authenticate(user=user)
        
        url = reverse('api-key-list')
        data = {
            'name': 'Test API Key',
            'scopes': ['chat:read', 'chat:write']
        }
        # Pass org_id explicitly in header
        response = self.client.post(url, data, format='json', HTTP_X_ORG_ID=str(org.id))
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIn('token', response.data)
        self.assertIn('scopes', response.data)
        
        # Check API key was created
        api_key = APIKey.objects.get(name='Test API Key')
        self.assertEqual(api_key.org_id, org.id)
        self.assertEqual(api_key.scopes, ['chat:read', 'chat:write'])
    
    def test_api_key_validation(self):
        """Test API key scope validation"""
        # Create user and organization
        user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User',
            password='testpass123',
            is_email_verified=True
        )
        
        org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        Membership.objects.create(user=user, organization=org, role='owner')
        
        # Authenticate
        self.client.force_authenticate(user=user)
        self.client.defaults['HTTP_X_ORG_ID'] = str(org.id)
        
        url = reverse('api-key-list')
        data = {
            'name': 'Test API Key',
            'scopes': ['invalid:scope']
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid scope', response.data['error'])


class OrganizationAPITestCase(APITestCase):
    """Test organization API endpoints"""
    
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
        
        # Authenticate
        self.client.force_authenticate(user=self.user)
        self.client.defaults['HTTP_X_ORG_ID'] = str(self.org.id)
    
    def test_organization_list(self):
        """Test organization list endpoint"""
        url = reverse('organization-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_organization_detail(self):
        """Test organization detail endpoint"""
        url = reverse('organization-detail', kwargs={'pk': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Test Organization')
    
    def test_organization_creation(self):
        """Test organization creation"""
        url = reverse('organization-list')
        data = {
            'name': 'New Organization',
            'slug': 'new-org'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Organization')
        
        # Check organization was created
        self.assertTrue(Organization.objects.filter(slug='new-org').exists())
