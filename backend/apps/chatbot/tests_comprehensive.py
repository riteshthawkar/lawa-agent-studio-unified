"""
Comprehensive tests for chatbot API endpoints
"""
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
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from apps.indexing.models import IndexingJob

User = get_user_model()


class ChatbotAPITestCase(APITestCase):
    """Base test case for chatbot API tests"""
    
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
            verification_token="test-token",
            verified_at=timezone.now(),
            status="active"
        )
        
        self.chatbot = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name="Test Chatbot",
            description="Test chatbot description",
            config={
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        )
        
        # Authenticate user
        self.client.force_authenticate(user=self.user)


class ChatbotIndexInfoAPITests(APITestCase):
    """Comprehensive tests for chatbot index info API"""
    
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
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            verification_token="test-token",
            verified_at=timezone.now(),
            status="active",
            pinecone_index="lawa-website-index"
        )
        
        self.chatbot = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name="Test Chatbot",
            description="Test chatbot description",
            config={
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        )
    
    def test_chatbot_index_info_success(self):
        """Test successful chatbot index info retrieval"""
        # Create completed indexing job
        IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            external_job_id="job_123",
            task_id="task_456",
            url="https://example.com",
            status="completed",
            documents_indexed=420,
            embed_model="Qwen/Qwen3-Embedding-0.6B",
            completed_at=timezone.now()
        )
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertIn('site', data)
        self.assertIn('indexing_info', data)
        self.assertIn('chatbot_config', data)
        self.assertIn('api_endpoints', data)
        
        # Check site data
        self.assertEqual(data['site']['domain'], 'https://example.com')
        self.assertEqual(data['site']['org_id'], str(self.org.id))
        self.assertTrue(data['site']['verified'])
        
        # Check indexing info
        self.assertEqual(data['indexing_info']['pinecone_index'], 'lawa-website-index')
        self.assertEqual(data['indexing_info']['total_documents'], 420)
        self.assertEqual(data['indexing_info']['embed_model'], 'Qwen/Qwen3-Embedding-0.6B')
        
        # Check chatbot config
        self.assertEqual(data['chatbot_config']['name'], 'Test Chatbot')
        self.assertEqual(data['chatbot_config']['model'], 'gpt-3.5-turbo')
        self.assertEqual(data['chatbot_config']['temperature'], 0.7)
    
    def test_chatbot_index_info_domain_variations(self):
        """Test chatbot index info with different domain formats"""
        url = reverse('chatbot-index-info')
        
        # Test with different domain formats
        test_domains = [
            'https://example.com',
            'http://example.com',
            'example.com',
            'https://example.com/',
            'https://example.com/path'
        ]
        
        for domain in test_domains:
            params = {
                'domain': domain,
                'api_key': self.chatbot.api_key
            }
            
            response = self.client.get(url, params)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()['site']['domain'], 'https://example.com')
    
    def test_chatbot_index_info_missing_parameters(self):
        """Test chatbot index info with missing parameters"""
        url = reverse('chatbot-index-info')
        
        # Missing domain
        params = {'api_key': self.chatbot.api_key}
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Missing required parameters', response.json()['error'])
        
        # Missing API key
        params = {'domain': 'https://example.com'}
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Missing required parameters', response.json()['error'])
    
    def test_chatbot_index_info_invalid_api_key(self):
        """Test chatbot index info with invalid API key"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': 'invalid-api-key'
        }
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_chatbot_index_info_inactive_chatbot(self):
        """Test chatbot index info with inactive chatbot"""
        self.chatbot.status = 'inactive'
        self.chatbot.save()
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_chatbot_index_info_site_not_found(self):
        """Test chatbot index info with non-existent site"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://nonexistent.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.json()['error'])
    
    def test_chatbot_index_info_unverified_site(self):
        """Test chatbot index info with unverified site"""
        # Create unverified site
        unverified_site = Site.objects.create(
            org_id=self.org.id,
            domain="https://unverified.com",
            verification_token="test-token",
            status="pending"
        )
        
        chatbot = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=unverified_site.id,
            name="Unverified Chatbot",
            api_key="test-api-key"
        )
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://unverified.com',
            'api_key': chatbot.api_key
        }
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.json()['error'])
    
    def test_chatbot_index_info_no_indexing_job(self):
        """Test chatbot index info with no completed indexing job"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check that indexing info has default values
        indexing_info = response.json()['indexing_info']
        self.assertEqual(indexing_info['total_documents'], 0)
        self.assertEqual(indexing_info['embed_model'], 'Qwen/Qwen3-Embedding-0.6B')
        self.assertIsNone(indexing_info['last_indexed_at'])
    
    def test_chatbot_index_info_namespace_calculation(self):
        """Test namespace calculation in index info"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        indexing_info = response.json()['indexing_info']
        expected_namespace = f"tenant_{self.org.id}__site_{self.site.id}"
        self.assertEqual(indexing_info['namespace'], expected_namespace)
    
    def test_chatbot_index_info_with_namespace_override(self):
        """Test namespace override in index info"""
        # Set namespace override on site
        self.site.namespace_override = "custom_namespace"
        self.site.save()
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        indexing_info = response.json()['indexing_info']
        self.assertEqual(indexing_info['namespace'], 'custom_namespace')
        self.assertEqual(indexing_info['namespace_override'], 'custom_namespace')
    
    def test_chatbot_index_info_rate_limiting(self):
        """Test rate limiting on chatbot index info endpoint"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        # Make multiple requests quickly
        for _ in range(105):  # Exceed rate limit
            response = self.client.get(url, params)
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                break
        
        # Should eventually hit rate limit
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS])


class ChatbotManagementAPITests(ChatbotAPITestCase):
    """Comprehensive tests for chatbot management API"""
    
    def test_chatbot_list_success(self):
        """Test successful chatbot list retrieval"""
        url = reverse('chatbots-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertIn('count', data)
        self.assertIn('results', data)
        self.assertIn('filters', data)
        
        self.assertEqual(data['count'], 1)
        self.assertEqual(len(data['results']), 1)
        
        chatbot_data = data['results'][0]
        self.assertEqual(chatbot_data['name'], 'Test Chatbot')
        self.assertEqual(chatbot_data['status'], 'active')
        self.assertEqual(chatbot_data['is_active'], True)
        self.assertEqual(chatbot_data['site_domain'], 'https://example.com')
    
    def test_chatbot_list_with_filters(self):
        """Test chatbot list with various filters"""
        # Create additional chatbots
        Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name="Inactive Chatbot",
            status="inactive"
        )
        
        Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name="Draft Chatbot",
            status="draft"
        )
        
        url = reverse('chatbots-management')
        
        # Test status filter
        response = self.client.get(url, {'status': 'active'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['status'], 'active')
        
        # Test site filter
        response = self.client.get(url, {'site_id': str(self.site.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 3)
        
        # Test search filter
        response = self.client.get(url, {'search': 'Inactive'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['name'], 'Inactive Chatbot')
    
    def test_chatbot_list_pagination(self):
        """Test chatbot list pagination"""
        # Create multiple chatbots
        for i in range(25):
            Chatbot.objects.create(
                org_id=self.org.id,
                site_id=self.site.id,
                name=f"Chatbot {i}",
                status="active"
            )
        
        url = reverse('chatbots-management')
        response = self.client.get(url, {'page': 1, 'page_size': 10})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 26)  # 25 new + 1 existing
        self.assertEqual(len(data['results']), 10)
        self.assertIsNotNone(data['next'])
        self.assertIsNone(data['previous'])
    
    def test_chatbot_list_ordering(self):
        """Test chatbot list ordering"""
        # Create chatbots with different names
        chatbot1 = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name="Alpha Chatbot",
            status="active"
        )
        
        chatbot2 = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name="Beta Chatbot",
            status="active"
        )
        
        url = reverse('chatbots-management')
        
        # Test ordering by name
        response = self.client.get(url, {'ordering': 'name'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        names = [chatbot['name'] for chatbot in data['results']]
        self.assertEqual(names, sorted(names))
        
        # Test ordering by name descending
        response = self.client.get(url, {'ordering': '-name'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        names = [chatbot['name'] for chatbot in data['results']]
        self.assertEqual(names, sorted(names, reverse=True))
    
    def test_chatbot_list_no_organization(self):
        """Test chatbot list when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('chatbots-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('User not associated with any organization', response.json()['error'])
    
    def test_chatbot_list_unauthorized(self):
        """Test chatbot list without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('chatbots-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_chatbot_list_with_sessions(self):
        """Test chatbot list with session data"""
        # Create chat sessions
        ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user_id="user_1",
            created_at=timezone.now() - timedelta(days=10)
        )
        
        ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user_id="user_2",
            created_at=timezone.now() - timedelta(days=5)
        )
        
        url = reverse('chatbots-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        chatbot_data = data['results'][0]
        self.assertEqual(chatbot_data['sessions_count'], 2)
        self.assertIsNotNone(chatbot_data['last_activity'])
    
    def test_chatbot_list_model_info(self):
        """Test chatbot list model info"""
        url = reverse('chatbots-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        chatbot_data = data['results'][0]
        self.assertIn('model_info', chatbot_data)
        self.assertEqual(chatbot_data['model_info']['model'], 'gpt-3.5-turbo')
        self.assertEqual(chatbot_data['model_info']['temperature'], 0.7)
        self.assertEqual(chatbot_data['model_info']['max_tokens'], 1000)


class ChatbotCreateAPITests(ChatbotAPITestCase):
    """Comprehensive tests for chatbot creation API"""
    
    def test_create_chatbot_success(self):
        """Test successful chatbot creation"""
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-4',
                'temperature': 0.5,
                'max_tokens': 2000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        response_data = response.json()
        self.assertIn('id', response_data)
        self.assertEqual(response_data['name'], 'New Chatbot')
        self.assertEqual(response_data['description'], 'New chatbot description')
        self.assertEqual(response_data['status'], 'active')
        self.assertIn('api_key', response_data)
        self.assertIn('embed_code', response_data)
        self.assertEqual(response_data['config']['model'], 'gpt-4')
        
        # Verify chatbot was created in database
        chatbot = Chatbot.objects.get(name='New Chatbot')
        self.assertEqual(chatbot.org_id, self.org.id)
        self.assertEqual(chatbot.site_id, self.site.id)
        self.assertEqual(chatbot.status, 'active')
    
    def test_create_chatbot_site_not_found(self):
        """Test chatbot creation with non-existent site"""
        url = reverse('create-chatbot', kwargs={'site_id': uuid.uuid4()})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.json()['error'])
    
    def test_create_chatbot_site_not_verified(self):
        """Test chatbot creation with unverified site"""
        # Create unverified site
        unverified_site = Site.objects.create(
            org_id=self.org.id,
            domain="https://unverified.com",
            verification_token="token",
            status="pending"
        )
        
        url = reverse('create-chatbot', kwargs={'site_id': unverified_site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Site must be verified and active', response.json()['error'])
    
    def test_create_chatbot_quota_exceeded(self):
        """Test chatbot creation when quota is exceeded"""
        # Set quota limit to 0
        from apps.usage.models import Quota
        Quota.objects.create(
            org_id=self.org.id,
            sites_limit=10,
            indexing_jobs_limit=100,
            chat_sessions_limit=1000,
            chatbots_limit=0
        )
        
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Chatbot limit exceeded', response.json()['error'])
    
    def test_create_chatbot_no_organization(self):
        """Test chatbot creation when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('User not associated with any organization', response.json()['error'])
    
    def test_create_chatbot_unauthorized(self):
        """Test chatbot creation without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_create_chatbot_validation_errors(self):
        """Test chatbot creation with validation errors"""
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        
        # Test missing required fields
        data = {
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.json())
        
        # Test invalid config
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 3.0,  # Invalid temperature
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('config', response.json())
        
        # Test missing config fields
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo'
                # Missing temperature and max_tokens
            }
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('config', response.json())
    
    def test_create_chatbot_api_key_generation(self):
        """Test chatbot creation API key generation"""
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        response_data = response.json()
        self.assertIn('api_key', response_data)
        self.assertTrue(response_data['api_key'].startswith('cb_'))
        self.assertEqual(len(response_data['api_key']), 35)
    
    def test_create_chatbot_embed_code_generation(self):
        """Test chatbot creation embed code generation"""
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        response_data = response.json()
        self.assertIn('embed_code', response_data)
        self.assertIn('apiKey', response_data['embed_code'])
        self.assertIn(response_data['api_key'], response_data['embed_code'])
        self.assertIn(str(self.site.id), response_data['embed_code'])
    
    def test_create_chatbot_error_handling(self):
        """Test chatbot creation error handling"""
        url = reverse('create-chatbot', kwargs={'site_id': self.site.id})
        
        # Test with invalid JSON
        response = self.client.post(
            url,
            'invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ChatbotUpdateAPITests(ChatbotAPITestCase):
    """Comprehensive tests for chatbot update API"""
    
    def test_update_chatbot_success(self):
        """Test successful chatbot update"""
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        data = {
            'name': 'Updated Chatbot',
            'description': 'Updated description',
            'config': {
                'model': 'gpt-4',
                'temperature': 0.5,
                'max_tokens': 2000
            },
            'status': 'active'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        response_data = response.json()
        self.assertEqual(response_data['name'], 'Updated Chatbot')
        self.assertEqual(response_data['description'], 'Updated description')
        self.assertEqual(response_data['config']['model'], 'gpt-4')
        self.assertEqual(response_data['status'], 'active')
        
        # Verify chatbot was updated in database
        self.chatbot.refresh_from_db()
        self.assertEqual(self.chatbot.name, 'Updated Chatbot')
        self.assertEqual(self.chatbot.description, 'Updated description')
        self.assertEqual(self.chatbot.config['model'], 'gpt-4')
        self.assertEqual(self.chatbot.status, 'active')
    
    def test_update_chatbot_not_found(self):
        """Test chatbot update with non-existent chatbot"""
        url = reverse('update-chatbot', kwargs={'chatbot_id': uuid.uuid4()})
        data = {
            'name': 'Updated Chatbot'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Chatbot not found', response.json()['error'])
    
    def test_update_chatbot_no_organization(self):
        """Test chatbot update when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        data = {
            'name': 'Updated Chatbot'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Chatbot not found', response.json()['error'])
    
    def test_update_chatbot_unauthorized(self):
        """Test chatbot update without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        data = {
            'name': 'Updated Chatbot'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_update_chatbot_validation_errors(self):
        """Test chatbot update with validation errors"""
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        
        # Test invalid config
        data = {
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 3.0,  # Invalid temperature
                'max_tokens': 1000
            }
        }
        
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('config', response.json())
    
    def test_update_chatbot_no_valid_fields(self):
        """Test chatbot update with no valid fields"""
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        data = {
            'invalid_field': 'value'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('No valid fields to update', response.json()['error'])
    
    def test_update_chatbot_partial_update(self):
        """Test chatbot partial update"""
        url = reverse('update-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        data = {
            'name': 'Updated Name Only'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        response_data = response.json()
        self.assertEqual(response_data['name'], 'Updated Name Only')
        self.assertEqual(response_data['description'], 'Test chatbot description')  # Unchanged
        
        # Verify only name was updated
        self.chatbot.refresh_from_db()
        self.assertEqual(self.chatbot.name, 'Updated Name Only')
        self.assertEqual(self.chatbot.description, 'Test chatbot description')


class ChatbotDeleteAPITests(ChatbotAPITestCase):
    """Comprehensive tests for chatbot delete API"""
    
    def test_delete_chatbot_success(self):
        """Test successful chatbot deletion"""
        url = reverse('delete-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Chatbot deleted successfully', response.json()['message'])
        
        # Verify chatbot was deleted
        self.assertFalse(Chatbot.objects.filter(id=self.chatbot.id).exists())
    
    def test_delete_chatbot_not_found(self):
        """Test chatbot deletion with non-existent chatbot"""
        url = reverse('delete-chatbot', kwargs={'chatbot_id': uuid.uuid4()})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Chatbot not found', response.json()['error'])
    
    def test_delete_chatbot_no_organization(self):
        """Test chatbot deletion when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('delete-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Chatbot not found', response.json()['error'])
    
    def test_delete_chatbot_unauthorized(self):
        """Test chatbot deletion without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('delete-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_delete_chatbot_with_sessions(self):
        """Test chatbot deletion with associated sessions"""
        # Create chat sessions
        ChatSession.objects.create(
            org_id=self.org.id,
            chatbot_id=self.chatbot.id,
            site_id=self.site.id,
            user_id="user_1"
        )
        
        ChatMessage.objects.create(
            session=ChatSession.objects.first(),
            role="user",
            content="Hello"
        )
        
        url = reverse('delete-chatbot', kwargs={'chatbot_id': self.chatbot.id})
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify chatbot and associated data were deleted
        self.assertFalse(Chatbot.objects.filter(id=self.chatbot.id).exists())
        self.assertFalse(ChatSession.objects.filter(chatbot_id=self.chatbot.id).exists())
        self.assertFalse(ChatMessage.objects.filter(session__chatbot_id=self.chatbot.id).exists())
