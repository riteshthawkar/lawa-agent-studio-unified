"""
Comprehensive tests for indexing API endpoints
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
from apps.indexing.models import IndexingJob
from apps.indexing.services import IndexingService

User = get_user_model()


class IndexingAPITestCase(APITestCase):
    """Base test case for indexing API tests"""
    
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
        
        # Authenticate user
        self.client.force_authenticate(user=self.user)


class IndexingJobsManagementAPITests(IndexingAPITestCase):
    """Comprehensive tests for indexing jobs management API"""
    
    def test_indexing_jobs_list_success(self):
        """Test successful indexing jobs list retrieval"""
        # Create test indexing job
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed",
            documents_indexed=100
        )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertIn('count', data)
        self.assertIn('results', data)
        self.assertIn('filters', data)
        
        self.assertEqual(data['count'], 1)
        self.assertEqual(len(data['results']), 1)
        
        job_data = data['results'][0]
        self.assertEqual(job_data['site_domain'], 'https://example.com')
        self.assertEqual(job_data['status'], 'completed')
        self.assertEqual(job_data['documents_indexed'], 100)
        self.assertEqual(job_data['progress_percentage'], 100)
        self.assertFalse(job_data['can_cancel'])
        self.assertFalse(job_data['can_retry'])
    
    def test_indexing_jobs_list_with_filters(self):
        """Test indexing jobs list with various filters"""
        # Create jobs with different statuses
        job1 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed"
        )
        
        job2 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="failed",
            error_message="Test error"
        )
        
        job3 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="processing"
        )
        
        url = reverse('indexing-jobs-management')
        
        # Test status filter
        response = self.client.get(url, {'status': 'completed'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['status'], 'completed')
        
        # Test site filter
        response = self.client.get(url, {'site_id': str(self.site.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 3)
        
        # Test search filter
        response = self.client.get(url, {'search': 'Test error'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['error_message'], 'Test error')
    
    def test_indexing_jobs_list_pagination(self):
        """Test indexing jobs list pagination"""
        # Create multiple jobs
        for i in range(25):
            IndexingJob.objects.create(
                org_id=self.org.id,
                site_id=self.site.id,
                url=f"https://example{i}.com",
                status="completed"
            )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url, {'page': 1, 'page_size': 10})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 25)
        self.assertEqual(len(data['results']), 10)
        self.assertIsNotNone(data['next'])
        self.assertIsNone(data['previous'])
    
    def test_indexing_jobs_list_ordering(self):
        """Test indexing jobs list ordering"""
        # Create jobs with different creation times
        job1 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example1.com",
            status="completed"
        )
        
        job2 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example2.com",
            status="completed"
        )
        
        url = reverse('indexing-jobs-management')
        
        # Test ordering by created_at descending (default)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['results'][0]['id'], str(job2.id))
        self.assertEqual(data['results'][1]['id'], str(job1.id))
        
        # Test ordering by created_at ascending
        response = self.client.get(url, {'ordering': 'created_at'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['results'][0]['id'], str(job1.id))
        self.assertEqual(data['results'][1]['id'], str(job2.id))
    
    def test_indexing_jobs_list_no_organization(self):
        """Test indexing jobs list when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('User not associated with any organization', response.json()['error'])
    
    def test_indexing_jobs_list_unauthorized(self):
        """Test indexing jobs list without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_indexing_jobs_list_progress_calculation(self):
        """Test indexing jobs list progress calculation"""
        # Create job with progress
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="processing",
            max_pages=100,
            urls_processed=50
        )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        job_data = data['results'][0]
        self.assertEqual(job_data['progress_percentage'], 50)
    
    def test_indexing_jobs_list_duration_calculation(self):
        """Test indexing jobs list duration calculation"""
        # Create job with duration
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed",
            started_at=timezone.now() - timedelta(minutes=5, seconds=30),
            completed_at=timezone.now()
        )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        job_data = data['results'][0]
        self.assertIsNotNone(job_data['duration_formatted'])
        self.assertIn('5m', job_data['duration_formatted'])
        self.assertIn('30s', job_data['duration_formatted'])
    
    def test_indexing_jobs_list_can_cancel_retry(self):
        """Test indexing jobs list can cancel/retry flags"""
        # Create jobs with different statuses
        processing_job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="processing"
        )
        
        failed_job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="failed"
        )
        
        completed_job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed"
        )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        jobs = {job['id']: job for job in data['results']}
        
        # Processing job can be cancelled
        self.assertTrue(jobs[str(processing_job.id)]['can_cancel'])
        self.assertFalse(jobs[str(processing_job.id)]['can_retry'])
        
        # Failed job can be retried
        self.assertFalse(jobs[str(failed_job.id)]['can_cancel'])
        self.assertTrue(jobs[str(failed_job.id)]['can_retry'])
        
        # Completed job cannot be cancelled or retried
        self.assertFalse(jobs[str(completed_job.id)]['can_cancel'])
        self.assertFalse(jobs[str(completed_job.id)]['can_retry'])


class IndexingJobCreateAPITests(IndexingAPITestCase):
    """Comprehensive tests for indexing job creation API"""
    
    @patch('apps.indexing.services.IndexingService._call_indexing_service')
    def test_create_indexing_job_success(self, mock_call_service):
        """Test successful indexing job creation"""
        # Mock external service call
        mock_call_service.return_value = {
            'task_id': 'task_123',
            'status': 'queued'
        }
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100,
            'embed_model': 'Qwen/Qwen3-Embedding-0.6B'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        response_data = response.json()
        self.assertIn('id', response_data)
        self.assertIn('external_job_id', response_data)
        self.assertIn('task_id', response_data)
        self.assertEqual(response_data['status'], 'queued')
        self.assertEqual(response_data['url'], 'https://example.com')
        self.assertEqual(response_data['max_pages'], 100)
        
        # Verify job was created in database
        job = IndexingJob.objects.get(external_job_id=response_data['external_job_id'])
        self.assertEqual(job.org_id, self.org.id)
        self.assertEqual(job.site_id, self.site.id)
        self.assertEqual(job.url, 'https://example.com')
        self.assertEqual(job.max_pages, 100)
        
        # Verify external service was called
        mock_call_service.assert_called_once()
    
    def test_create_indexing_job_site_not_found(self):
        """Test indexing job creation with non-existent site"""
        url = reverse('create-indexing-job', kwargs={'site_id': uuid.uuid4()})
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Site not found', response.json()['error'])
    
    def test_create_indexing_job_site_not_verified(self):
        """Test indexing job creation with unverified site"""
        # Create unverified site
        unverified_site = Site.objects.create(
            org_id=self.org.id,
            domain="https://unverified.com",
            verification_token="token",
            status="pending"
        )
        
        url = reverse('create-indexing-job', kwargs={'site_id': unverified_site.id})
        data = {
            'url': 'https://unverified.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Site must be verified and active', response.json()['error'])
    
    def test_create_indexing_job_quota_exceeded(self):
        """Test indexing job creation when quota is exceeded"""
        # Set quota limit to 0
        from apps.usage.models import Quota
        Quota.objects.create(
            org_id=self.org.id,
            sites_limit=10,
            indexing_jobs_limit=0,
            chat_sessions_limit=1000
        )
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Indexing job limit exceeded', response.json()['error'])
    
    def test_create_indexing_job_no_organization(self):
        """Test indexing job creation when user has no organization"""
        # Remove user from organization
        self.membership.delete()
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('User not associated with any organization', response.json()['error'])
    
    def test_create_indexing_job_unauthorized(self):
        """Test indexing job creation without authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_create_indexing_job_validation_errors(self):
        """Test indexing job creation with validation errors"""
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        
        # Test invalid URL
        data = {
            'url': 'not-a-url',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('url', response.json())
        
        # Test invalid max_pages
        data = {
            'url': 'https://example.com',
            'max_pages': 0
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('max_pages', response.json())
        
        # Test max_pages too high
        data = {
            'url': 'https://example.com',
            'max_pages': 20000
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('max_pages', response.json())
    
    def test_create_indexing_job_missing_required_fields(self):
        """Test indexing job creation with missing required fields"""
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        
        # Test missing URL
        data = {
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('url', response.json())
    
    def test_create_indexing_job_with_optional_fields(self):
        """Test indexing job creation with optional fields"""
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100,
            'allowed_domains': ['example.com', 'sub.example.com'],
            'excluded_subdomains': ['admin.example.com'],
            'pinecone_index': 'custom-index',
            'embed_model': 'Qwen/Qwen3-Embedding-0.6B',
            'streaming_mode': True,
            'use_namespaces': True,
            'namespace_prefix': 'website_domain',
            'namespace_override': 'custom-namespace',
            'custom_config': {'key': 'value'}
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify job was created with optional fields
        job = IndexingJob.objects.get(url='https://example.com')
        self.assertEqual(job.allowed_domains, ['example.com', 'sub.example.com'])
        self.assertEqual(job.excluded_subdomains, ['admin.example.com'])
        self.assertEqual(job.pinecone_index, 'custom-index')
        self.assertEqual(job.embed_model, 'Qwen/Qwen3-Embedding-0.6B')
        self.assertTrue(job.streaming_mode)
        self.assertTrue(job.use_namespaces)
        self.assertEqual(job.namespace_prefix, 'website_domain')
        self.assertEqual(job.namespace_override, 'custom-namespace')
        self.assertEqual(job.custom_config, {'key': 'value'})
    
    @patch('apps.indexing.services.IndexingService._call_indexing_service')
    def test_create_indexing_job_external_service_error(self, mock_call_service):
        """Test indexing job creation when external service fails"""
        # Mock external service to raise exception
        mock_call_service.side_effect = Exception("External service error")
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('Internal server error', response.json()['error'])
    
    def test_create_indexing_job_error_handling(self):
        """Test indexing job creation error handling"""
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        
        # Test with invalid JSON
        response = self.client.post(
            url,
            'invalid json',
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class IndexingServiceTests(TestCase):
    """Comprehensive tests for IndexingService"""
    
    def setUp(self):
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
            status="active"
        )
    
    @patch('apps.indexing.services.IndexingService._call_indexing_service')
    def test_create_indexing_job_success(self, mock_call_service):
        """Test successful indexing job creation"""
        # Mock external service call
        mock_call_service.return_value = {
            'task_id': 'task_123',
            'status': 'queued'
        }
        
        service = IndexingService()
        params = {
            'url': 'https://example.com',
            'max_pages': 100,
            'embed_model': 'Qwen/Qwen3-Embedding-0.6B'
        }
        
        job = service.create_indexing_job(
            site=self.site,
            params=params,
            user_id=str(self.user.id)
        )
        
        self.assertIsNotNone(job)
        self.assertEqual(job.org_id, self.org.id)
        self.assertEqual(job.site_id, self.site.id)
        self.assertEqual(job.url, 'https://example.com')
        self.assertEqual(job.max_pages, 100)
        self.assertEqual(job.embed_model, 'Qwen/Qwen3-Embedding-0.6B')
        self.assertEqual(job.status, 'queued')
        
        # Verify external service was called
        mock_call_service.assert_called_once()
    
    @patch('apps.indexing.services.IndexingService._call_indexing_service')
    def test_create_indexing_job_with_all_params(self, mock_call_service):
        """Test indexing job creation with all parameters"""
        # Mock external service call
        mock_call_service.return_value = {
            'task_id': 'task_123',
            'status': 'queued'
        }
        
        service = IndexingService()
        params = {
            'url': 'https://example.com',
            'max_pages': 100,
            'allowed_domains': ['example.com'],
            'excluded_subdomains': ['admin.example.com'],
            'pinecone_index': 'custom-index',
            'embed_model': 'Qwen/Qwen3-Embedding-0.6B',
            'streaming_mode': True,
            'use_namespaces': True,
            'namespace_prefix': 'website_domain',
            'namespace_override': 'custom-namespace',
            'custom_config': {'key': 'value'}
        }
        
        job = service.create_indexing_job(
            site=self.site,
            params=params,
            user_id=str(self.user.id)
        )
        
        self.assertEqual(job.allowed_domains, ['example.com'])
        self.assertEqual(job.excluded_subdomains, ['admin.example.com'])
        self.assertEqual(job.pinecone_index, 'custom-index')
        self.assertEqual(job.embed_model, 'Qwen/Qwen3-Embedding-0.6B')
        self.assertTrue(job.streaming_mode)
        self.assertTrue(job.use_namespaces)
        self.assertEqual(job.namespace_prefix, 'website_domain')
        self.assertEqual(job.namespace_override, 'custom-namespace')
        self.assertEqual(job.custom_config, {'key': 'value'})
    
    def test_update_job_status_success(self):
        """Test successful job status update"""
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            external_job_id="job_123"
        )
        
        service = IndexingService()
        
        # Test status transitions
        service.update_job_status(job.external_job_id, 'processing')
        job.refresh_from_db()
        self.assertEqual(job.status, 'processing')
        self.assertIsNotNone(job.started_at)
        
        service.update_job_status(job.external_job_id, 'collecting_urls')
        job.refresh_from_db()
        self.assertEqual(job.status, 'collecting_urls')
        
        service.update_job_status(job.external_job_id, 'processing_urls')
        job.refresh_from_db()
        self.assertEqual(job.status, 'processing_urls')
        
        service.update_job_status(job.external_job_id, 'completed')
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertIsNotNone(job.completed_at)
    
    def test_update_job_status_with_progress(self):
        """Test job status update with progress data"""
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            external_job_id="job_123"
        )
        
        service = IndexingService()
        progress_data = {
            'urls_collected': 50,
            'urls_processed': 30,
            'documents_indexed': 25
        }
        
        service.update_job_status(
            job.external_job_id,
            'processing',
            progress_data=progress_data
        )
        
        job.refresh_from_db()
        self.assertEqual(job.urls_collected, 50)
        self.assertEqual(job.urls_processed, 30)
        self.assertEqual(job.documents_indexed, 25)
    
    def test_update_job_status_with_error(self):
        """Test job status update with error"""
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            external_job_id="job_123"
        )
        
        service = IndexingService()
        service.update_job_status(
            job.external_job_id,
            'failed',
            error_message="Test error"
        )
        
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_message, "Test error")
    
    def test_update_job_status_not_found(self):
        """Test job status update with non-existent job"""
        service = IndexingService()
        
        with self.assertRaises(IndexingJob.DoesNotExist):
            service.update_job_status('non_existent_job', 'completed')
    
    def test_build_callback_url(self):
        """Test callback URL building"""
        service = IndexingService()
        
        with patch('django.conf.settings.ALLOWED_HOSTS', ['api.example.com']):
            url = service._build_callback_url()
            self.assertIn('api.example.com', url)
            self.assertIn('webhooks/indexing', url)
        
        with patch('django.conf.settings.ALLOWED_HOSTS', []):
            url = service._build_callback_url()
            self.assertIn('localhost', url)
            self.assertIn('webhooks/indexing', url)
    
    @patch('requests.post')
    def test_call_indexing_service_success(self, mock_post):
        """Test successful external service call"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'task_id': 'task_123',
            'status': 'queued'
        }
        mock_post.return_value = mock_response
        
        service = IndexingService()
        params = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        result = service._call_indexing_service(
            site=self.site,
            params=params,
            job_id="job_123"
        )
        
        self.assertEqual(result['task_id'], 'task_123')
        self.assertEqual(result['status'], 'queued')
        
        # Verify request was made correctly
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]['json']['url'], 'https://example.com')
        self.assertEqual(call_args[1]['json']['max_pages'], 100)
        self.assertEqual(call_args[1]['json']['tenant_id'], str(self.org.id))
        self.assertEqual(call_args[1]['json']['site_id'], str(self.site.id))
        self.assertEqual(call_args[1]['json']['external_job_id'], 'job_123')
    
    @patch('requests.post')
    def test_call_indexing_service_failure(self, mock_post):
        """Test external service call failure"""
        # Mock failed response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {'error': 'Bad request'}
        mock_post.return_value = mock_response
        
        service = IndexingService()
        params = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        with self.assertRaises(Exception):
            service._call_indexing_service(
                site=self.site,
                params=params,
                job_id="job_123"
            )
    
    @patch('requests.post')
    def test_call_indexing_service_network_error(self, mock_post):
        """Test external service call network error"""
        # Mock network error
        mock_post.side_effect = Exception("Network error")
        
        service = IndexingService()
        params = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        with self.assertRaises(Exception):
            service._call_indexing_service(
                site=self.site,
                params=params,
                job_id="job_123"
            )
