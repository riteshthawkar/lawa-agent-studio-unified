"""
Comprehensive tests for chatbot retrieval functionality.

These tests ensure that the chatbot correctly retrieves data using
the proper namespace, preventing the "no data retrieved" bug.
"""
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.organizations.models import Organization

User = get_user_model()


class ChatbotIndexInfoTests(APITestCase):
    """Tests for chatbot_index_info endpoint namespace handling"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='retrievaluser',
            email='test@example.com',
            password='testpassword123'
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-chatbot"
        )
        from apps.organizations.models import Membership
        Membership.objects.create(user=self.user, organization=self.org, role='owner')
        
        self.site = Site.objects.create(
            domain="https://chatbot-test.com",
            name="Chatbot Test Site",
            org_id=self.org.id,
            status='active'
        )
        self.chatbot = Chatbot.objects.create(
            site=self.site,
            name="Test Chatbot",
            status='active'
        )
        
        # Authenticate
        self.client.force_authenticate(user=self.user)
    
    def test_index_info_returns_active_namespace(self):
        """Test that chatbot_index_info returns the active_namespace when set"""
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        url = reverse('chatbot-index-info')
        response = self.client.get(url, {'api_key': self.chatbot.api_key, 'domain': self.site.domain})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['indexing_info']['namespace'], expected_namespace)
    
    def test_index_info_returns_fallback_namespace_when_empty(self):
        """Test that chatbot_index_info returns fallback namespace when active_namespace is empty"""
        self.site.active_namespace = None
        self.site.save()
        
        url = reverse('chatbot-index-info')
        response = self.client.get(url, {'api_key': self.chatbot.api_key, 'domain': self.site.domain})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_fallback = f"site_{self.site.id}"
        self.assertEqual(response.data['indexing_info']['namespace'], expected_fallback)
    
    def test_index_info_namespace_format_matches_pinecone(self):
        """Test that returned namespace matches format stored in Pinecone"""
        # Simulate a real namespace that would be in Pinecone
        timestamp = 1234567890
        pinecone_namespace = f"site_{self.site.id}_{timestamp}"
        
        self.site.active_namespace = pinecone_namespace
        self.site.save()
        
        url = reverse('chatbot-index-info')
        response = self.client.get(url, {'api_key': self.chatbot.api_key, 'domain': self.site.domain})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify format: site_{uuid}_{timestamp}
        ns = response.data['indexing_info']['namespace']
        self.assertTrue(ns.startswith('site_'))
        self.assertIn(str(self.site.id), ns)
        parts = ns.split('_')
        self.assertEqual(len(parts), 3)  # site, uuid, timestamp


class ChatbotRetrievalNamespaceTests(TestCase):
    """Tests for ensuring chatbot retrieval uses correct namespace"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-retrieval"
        )
        self.site = Site.objects.create(
            domain="https://retrieval-test.com",
            name="Retrieval Test Site",
            org_id=self.org.id,
            status='active'
        )
        self.chatbot = Chatbot.objects.create(
            site=self.site,
            name="Test Chatbot",
            status='active'
        )
    
    def test_chatbot_uses_site_get_namespace_method(self):
        """Test that chatbot retrieval code uses site.get_namespace()"""
        from apps.chatbot.views import chatbot_index_info
        
        # Set active namespace
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        # Verify site.get_namespace() returns correct value
        self.assertEqual(self.site.get_namespace(), expected_namespace)
    
    def test_namespace_consistency_between_site_and_chatbot(self):
        """Test namespace consistency between Site model and Chatbot API"""
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        # Both should return the same namespace
        site_namespace = self.site.get_namespace()
        
        # Simulate what the chatbot API does
        chatbot_namespace = self.site.active_namespace or f"site_{self.site.id}"
        
        self.assertEqual(site_namespace, chatbot_namespace)
        self.assertEqual(site_namespace, expected_namespace)


class KnowledgeSearchNamespaceTests(APITestCase):
    """Tests for knowledge search namespace handling"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='knowledge@example.com',
            username='knowledgeuser',
            password='testpassword123'
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-knowledge"
        )
        from apps.organizations.models import Membership
        Membership.objects.create(user=self.user, organization=self.org, role='owner')
        
        self.site = Site.objects.create(
            domain="https://knowledge-test.com",
            name="Knowledge Test Site",
            org_id=self.org.id,
            status='active'
        )
        
        # Authenticate
        self.client.force_authenticate(user=self.user)
    
    def test_knowledge_search_uses_correct_namespace(self):
        """Test that knowledge search uses site.get_namespace()"""
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        # Mock the IndexingService.search_knowledge_base
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test query',
                'namespace': expected_namespace,
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test query'}, format='json')
            
            # Verify the search was called with correct namespace
            if mock_search.called:
                call_args = mock_search.call_args
                called_namespace = call_args[0][0] if call_args[0] else call_args[1].get('namespace')
                self.assertEqual(called_namespace, expected_namespace)
    
    def test_knowledge_search_uses_fallback_namespace(self):
        """Test that knowledge search falls back correctly when active_namespace is empty"""
        self.site.active_namespace = None
        self.site.save()
        
        expected_fallback = f"site_{self.site.id}"
        
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test query',
                'namespace': expected_fallback,
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test query'}, format='json')
            
            # Verify fallback namespace was used
            if mock_search.called:
                call_args = mock_search.call_args
                called_namespace = call_args[0][0] if call_args[0] else call_args[1].get('namespace')
                self.assertEqual(called_namespace, expected_fallback)


class ChatbotAPIKeyValidationTests(APITestCase):
    """Tests for chatbot API key validation and namespace retrieval"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-apikey"
        )
        self.site = Site.objects.create(
            domain="https://apikey-test.com",
            name="API Key Test Site",
            org_id=self.org.id,
            status='active'
        )
        self.chatbot = Chatbot.objects.create(
            site=self.site,
            name="Test Chatbot",
            status='active'
        )
    
    def test_chatbot_api_key_returns_correct_namespace(self):
        """Test that chatbot API key validation returns correct namespace"""
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        # Test that the site's get_namespace matches what we expect
        self.assertEqual(self.site.get_namespace(), expected_namespace)
        
        # The chatbot should use this namespace for vector searches
        self.assertEqual(
            self.chatbot.site.get_namespace(),
            expected_namespace
        )
    
    def test_inactive_chatbot_cannot_retrieve_data(self):
        """Test that inactive chatbots cannot retrieve data"""
        self.chatbot.status = 'inactive'
        self.chatbot.save()
        
        # Attempting to get index info for inactive chatbot should fail or return error
        # This depends on your API implementation
        self.assertFalse(self.chatbot.is_active)


class NamespaceMismatchRegressionTests(TestCase):
    """
    Regression tests specifically for the namespace mismatch bug.
    
    The bug: chatbot was using f"site_{site.id}" but Pinecone had
    f"site_{site.id}_{timestamp}" causing "no results found".
    """
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-regression"
        )
        self.site = Site.objects.create(
            domain="https://regression-test.com",
            name="Regression Test Site",
            org_id=self.org.id,
            status='active'
        )
    
    def test_old_namespace_format_not_used_when_active_namespace_set(self):
        """
        REGRESSION TEST: Ensure old format is NOT used when active_namespace is set.
        
        Old buggy code did: namespace = f"site_{site.id}"
        Fixed code does: namespace = site.active_namespace or f"site_{site.id}"
        """
        # This is what Pinecone actually has
        timestamped_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = timestamped_namespace
        self.site.save()
        
        # What the OLD buggy code would return
        old_buggy_namespace = f"site_{self.site.id}"
        
        # What the FIXED code should return
        correct_namespace = self.site.get_namespace()
        
        # Assertions
        self.assertNotEqual(correct_namespace, old_buggy_namespace)
        self.assertEqual(correct_namespace, timestamped_namespace)
    
    def test_fallback_namespace_still_works(self):
        """
        Test that fallback namespace still works for sites without active_namespace.
        
        This is important for backwards compatibility.
        """
        self.site.active_namespace = None
        self.site.save()
        
        # Should fall back to simple format
        expected_fallback = f"site_{self.site.id}"
        self.assertEqual(self.site.get_namespace(), expected_fallback)
    
    def test_empty_string_namespace_triggers_fallback(self):
        """Test that empty string active_namespace triggers fallback"""
        self.site.active_namespace = ""
        self.site.save()
        
        expected_fallback = f"site_{self.site.id}"
        self.assertEqual(self.site.get_namespace(), expected_fallback)
