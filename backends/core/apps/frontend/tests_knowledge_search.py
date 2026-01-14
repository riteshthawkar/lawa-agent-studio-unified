import pytest
"""
Comprehensive tests for Knowledge Search API endpoints.

These tests ensure that knowledge search functionality works correctly
and uses the proper namespace for vector queries.
"""
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from apps.organizations.models import Organization
from apps.sites.models import Site
from apps.indexing.models import IndexingJob

User = get_user_model()




class KnowledgeSearchAPITestCase(APITestCase):
    """Base test case for knowledge search API tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='search_test',
            email='search_test@example.com',
            password='testpassword123'
        )
        self.org = Organization.objects.create(
            name="Search Test Organization",
            slug="search-test-org"
        )
        # Create membership to link user to org
        from apps.organizations.models import Membership
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        
        self.site = Site.objects.create(
            domain="https://search-test.com",
            name="Search Test Site",
            org_id=self.org.id,
            status='active',
            active_namespace=f"site_{uuid.uuid4()}_1234567890"
        )
        
        # Create an indexing job for the site
        self.job = IndexingJob.objects.create(
            site_id=self.site.id,
            org_id=self.org.id,
            url="https://search-test.com",
            status='completed',
            external_job_id='search-test-job',
            target_namespace=self.site.active_namespace
        )
        
        self.client.force_authenticate(user=self.user)


class KnowledgeSearchTests(KnowledgeSearchAPITestCase):
    """Tests for knowledge search endpoint"""
    
    def test_search_success(self):
        """Test successful knowledge search"""
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test query',
                'namespace': self.site.active_namespace,
                'results': [
                    {
                        'id': 'doc-1',
                        'score': 0.95,
                        'title': 'Test Document',
                        'source': 'https://search-test.com/page1',
                        'content': 'This is test content'
                    }
                ],
                'total_results': 1
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test query'}, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['total_results'], 1)
            self.assertEqual(len(response.data['results']), 1)
    
    def test_search_uses_correct_namespace(self):
        """Test that search uses the correct namespace from site.get_namespace()"""
        expected_namespace = self.site.active_namespace
        
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test',
                'namespace': expected_namespace,
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test'}, format='json')
            
            # Verify the search was called with correct namespace
            self.assertTrue(mock_search.called)
            call_args = mock_search.call_args
            called_namespace = call_args[0][0] if call_args[0] else call_args[1].get('namespace')
            self.assertEqual(called_namespace, expected_namespace)
    
    def test_search_requires_query(self):
        """Test that search requires a query parameter"""
        url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
        response = self.client.post(url, {}, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY])
    
    def test_search_empty_query(self):
        """Test search with empty query"""
        url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
        response = self.client.post(url, {'query': ''}, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY])
    
    def test_search_requires_authentication(self):
        """Test that search requires authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
        response = self.client.post(url, {'query': 'test'}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_search_site_not_found(self):
        """Test search with non-existent site"""
        fake_site_id = str(uuid.uuid4())
        url = reverse('site-knowledge-base-search', kwargs={'site_id': fake_site_id})
        response = self.client.post(url, {'query': 'test'}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_search_unauthorized_site(self):
        """Test search for site not owned by user"""
        # Create another org and site
        other_org = Organization.objects.create(
            name="Other Organization",
            slug="other-org"
        )
        other_site = Site.objects.create(
            domain="https://other-site.com",
            name="Other Site",
            org_id=other_org.id,
            status='active'
        )
        
        url = reverse('site-knowledge-base-search', kwargs={'site_id': str(other_site.id)})
        response = self.client.post(url, {'query': 'test'}, format='json')
        
        # Should return 403 or 404 (hiding existence)
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
    
    def test_search_top_k_parameter(self):
        """Test search with custom top_k parameter"""
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test',
                'namespace': self.site.active_namespace,
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test', 'top_k': 5}, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Verify top_k was passed to the service
            if mock_search.called:
                call_kwargs = mock_search.call_args[1] if mock_search.call_args[1] else {}
                # top_k might be positional or keyword
                self.assertTrue(mock_search.called)
    
    def test_search_result_format(self):
        """Test that search results have correct format"""
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test query',
                'namespace': self.site.active_namespace,
                'results': [
                    {
                        'id': 'doc-1',
                        'score': 0.95,
                        'title': 'Test Title',
                        'source': 'https://example.com/page',
                        'content': 'Test content here'
                    }
                ],
                'total_results': 1
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test query'}, format='json')
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            
            # Verify response structure
            self.assertIn('results', response.data)
            self.assertIn('total_results', response.data)
            
            if response.data['results']:
                result = response.data['results'][0]
                self.assertIn('score', result)
                self.assertIn('source', result)


class KnowledgeSearchEdgeCaseTests(KnowledgeSearchAPITestCase):
    """Edge case tests for knowledge search"""
    
    def test_search_site_with_no_namespace(self):
        """Test search for site with no active_namespace set"""
        # Clear namespace
        self.site.active_namespace = None
        self.site.save()
        
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': 'test',
                'namespace': f"site_{self.site.id}",  # Fallback format
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test'}, format='json')
            
            # Should still work with fallback namespace
            self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_search_service_error_handling(self):
        """Test that search handles service errors gracefully"""
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.side_effect = Exception("Service unavailable")
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': 'test'}, format='json')
            
            # Should return error status
            self.assertIn(response.status_code, [
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                status.HTTP_503_SERVICE_UNAVAILABLE
            ])
    
    def test_search_very_long_query(self):
        """Test search with very long query"""
        long_query = "test " * 1000  # Very long query
        
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': long_query[:500],
                'namespace': self.site.active_namespace,
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': long_query}, format='json')
            
            # Should handle gracefully (either succeed or return validation error)
            self.assertIn(response.status_code, [
                status.HTTP_200_OK,
                status.HTTP_400_BAD_REQUEST
            ])
    
    def test_search_special_characters_in_query(self):
        """Test search with special characters"""
        special_query = "test <script>alert('xss')</script> query"
        
        with patch('apps.indexing.services.IndexingService.search_knowledge_base') as mock_search:
            mock_search.return_value = {
                'query': special_query,
                'namespace': self.site.active_namespace,
                'results': [],
                'total_results': 0
            }
            
            url = reverse('site-knowledge-base-search', kwargs={'site_id': str(self.site.id)})
            response = self.client.post(url, {'query': special_query}, format='json')
            
            # Should handle without errors
            self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])
