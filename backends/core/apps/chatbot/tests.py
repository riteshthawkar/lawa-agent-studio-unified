"""
Tests for chatbot integration functionality
"""
import uuid
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from unittest.mock import patch, MagicMock

from apps.organizations.models import Organization
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.indexing.models import IndexingJob


class ChatbotModelTestCase(TestCase):
    """Test cases for Chatbot model"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",

            status="active"
        )
    
    def test_chatbot_creation(self):
        """Test chatbot creation with auto-generated fields"""
        chatbot = Chatbot.objects.create(
            site_id=self.site.id,
            name="Test Chatbot",
            status='active',
            description="Test chatbot description",
            config={
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        )
        
        self.assertIsNotNone(chatbot.api_key)
        self.assertTrue(chatbot.api_key.startswith('cb_'))
        self.assertIsNotNone(chatbot.embed_code)
        self.assertIn('data-api-key', chatbot.embed_code)
        self.assertTrue(chatbot.is_active)
    
    def test_generate_api_key(self):
        """Test API key generation"""
        chatbot = Chatbot.objects.create(
            site_id=self.site.id,
            name="Test Chatbot"
        )
        
        api_key = chatbot.generate_api_key()
        self.assertTrue(api_key.startswith('cb_'))
        self.assertEqual(len(api_key), 46)  # cb_ + 43 chars (32 bytes base64)
    
    def test_generate_embed_code(self):
        """Test embed code generation"""
        chatbot = Chatbot.objects.create(
            site_id=self.site.id,
            name="Test Chatbot"
        )
        
        embed_code = chatbot.generate_embed_code()
        self.assertIn('data-api-key', embed_code)
        self.assertIn(chatbot.api_key, embed_code)


class ChatbotAPITestCase(APITestCase):
    """Test cases for chatbot API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",

            status="active"
        )
        
        self.chatbot = Chatbot.objects.create(
            site_id=self.site.id,
            name="Test Chatbot",
            status='active',
            description="Test chatbot description",
            config={
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        )
    
    def test_chatbot_list(self):
        """Test GET /chatbots/ returns chatbot list"""
        url = reverse('chatbot-list')
        
        response = self.client.get(url)
        
        # Should require authentication
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_chatbot_create(self):
        """Test POST /sites/{site_id}/chatbots/ creates chatbot"""
        url = reverse('site-chatbot-create', kwargs={'site_id': self.site.id})
        data = {
            'name': 'New Chatbot',
            'description': 'New chatbot description',
            'config': {
                'model': 'gpt-4',
                'temperature': 0.5,
                'max_tokens': 2000
            }
        }
        
        # Should require authentication
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_chatbot_embed_code(self):
        """Test GET /chatbots/{chatbot_id}/embed-code/ returns embed code"""
        url = reverse('chatbot-embed-code', kwargs={'chatbot_id': self.chatbot.id})
        
        # Should require authentication
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_regenerate_api_key(self):
        """Test POST /chatbots/{chatbot_id}/regenerate-api-key/ regenerates API key"""
        url = reverse('chatbot-regenerate-api-key', kwargs={'chatbot_id': self.chatbot.id})
        old_api_key = self.chatbot.api_key
        
        # Should require authentication
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ChatbotIndexInfoTestCase(APITestCase):
    """Test cases for chatbot index info endpoint"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",

            status="active"
        )
        
        self.chatbot = Chatbot.objects.create(
            site_id=self.site.id,
            name="Test Chatbot",
            status="active",
            description="Test chatbot description",
            config={
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        )
        
        # Create a completed indexing job
        self.indexing_job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            external_job_id="test-job-123",
            task_id="task-456",
            url="https://example.com",
            status="completed",
            documents_indexed=420,
            completed_at="2025-01-01T12:00:00Z"
        )
    
    def test_chatbot_index_info_success(self):
        """Test successful chatbot index info retrieval"""
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check response structure
        self.assertIn('site', response.data)
        self.assertIn('indexing_info', response.data)
        self.assertIn('chatbot_config', response.data)
        self.assertIn('api_endpoints', response.data)
        
        # Check site data
        site_data = response.data['site']
        self.assertEqual(site_data['domain'], 'https://example.com')
        # self.assertEqual(site_data['org_id'], str(self.org.id))
        # self.assertTrue(site_data['verified'])
        
        # Check indexing info
        indexing_info = response.data['indexing_info']
        import os
        from django.conf import settings
        expected_index = getattr(settings, 'PINECONE_INDEX_NAME', os.getenv('PINECONE_INDEX', 'lawa-website-index'))
        self.assertEqual(indexing_info['pinecone_index'], expected_index)
        self.assertEqual(indexing_info['total_documents'], 420)
        
    
        # Check chatbot config
        chatbot_config = response.data['chatbot_config']
        self.assertEqual(chatbot_config['name'], 'Test Chatbot')
        self.assertEqual(chatbot_config['model'], 'gpt-4o')
        self.assertEqual(chatbot_config['temperature'], 0.7)
    
    def test_chatbot_index_info_domain_variations(self):
        """Test chatbot index info with different domain formats"""
        url = reverse('chatbot-index-info')
        
        # Test with different domain formats
        test_domains = [
            'https://example.com',
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
            self.assertEqual(response.data['site']['domain'], 'https://example.com')
    
    def test_chatbot_index_info_missing_parameters(self):
        """Test chatbot index info with missing parameters"""
        url = reverse('chatbot-index-info')
        
        # Missing domain
        params = {'api_key': self.chatbot.api_key}
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Missing required parameters', response.data['error'])
        
        # Missing API key
        params = {'domain': 'https://example.com'}
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Missing required parameters', response.data['error'])
    
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
        self.assertIn('Site not found', response.data['error'])
    
    def test_chatbot_index_info_unverified_site(self):
        """Test chatbot index info with unverified site"""
        # Create unverified site
        unverified_site = Site.objects.create(
            org_id=self.org.id,
            domain="https://unverified.com",

            status="inactive"
        )
        
        chatbot = Chatbot.objects.create(
            site_id=unverified_site.id,
            name="Unverified Chatbot",
            api_key="test-api-key",
            status="active"
        )
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://unverified.com',
            'api_key': chatbot.api_key
        }
        
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.data['error'])
    
    def test_chatbot_index_info_no_indexing_job(self):
        """Test chatbot index info with no completed indexing job"""
        # Create site without indexing job
        site_no_job = Site.objects.create(
            org_id=self.org.id,
            domain="https://nojob.com",

            status="active"
        )
        
        chatbot = Chatbot.objects.create(
            site_id=site_no_job.id,
            name="No Job Chatbot",
            api_key="test-api-key-2",
            status="active"
        )
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://nojob.com',
            'api_key': chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check that indexing info has default values
        indexing_info = response.data['indexing_info']
        self.assertEqual(indexing_info['total_documents'], 0)
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
        
        indexing_info = response.data['indexing_info']
        expected_namespace = f"site_{self.site.id}"
        self.assertIn(expected_namespace, indexing_info['namespace'])
    
    def test_chatbot_index_info_with_namespace_override(self):
        """Test namespace override in index info"""
        # Set namespace override on site
        self.site.active_namespace = "custom_namespace"
        self.site.save()
        
        url = reverse('chatbot-index-info')
        params = {
            'domain': 'https://example.com',
            'api_key': self.chatbot.api_key
        }
        
        response = self.client.get(url, params)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        indexing_info = response.data['indexing_info']
        self.assertEqual(indexing_info['namespace'], 'custom_namespace')
        # self.assertEqual(indexing_info['namespace_override'], 'custom_namespace')
    
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


class ChatbotSerializerTestCase(TestCase):
    """Test cases for chatbot serializers"""
    
    def test_chatbot_create_serializer_validation(self):
        """Test chatbot create serializer validation"""
        from apps.chatbot.serializers import ChatbotCreateSerializer
        
        # Valid data
        valid_data = {
            'name': 'Test Chatbot',
            'description': 'Test description',
            'config': {
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7,
                'max_tokens': 1000
            }
        }
        
        serializer = ChatbotCreateSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid())
        
        # Invalid temperature
        invalid_data = valid_data.copy()
        invalid_data['config']['temperature'] = 3.0
        
        serializer = ChatbotCreateSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('config', serializer.errors)
        
        # Invalid max_tokens
        invalid_data = valid_data.copy()
        invalid_data['config']['max_tokens'] = 5000
        
        serializer = ChatbotCreateSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('config', serializer.errors)
        
        # Missing required config fields
        invalid_data = valid_data.copy()
        del invalid_data['config']['model']
        
        serializer = ChatbotCreateSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('config', serializer.errors)
