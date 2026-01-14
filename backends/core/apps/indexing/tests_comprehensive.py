"""
Comprehensive tests for indexing API endpoints
"""
import pytest
import json
import uuid
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.test import override_settings

from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.indexing.services import IndexingService
from apps.usage.models import Quota

User = get_user_model()


class IndexingAPITestCase(APITestCase):
    """Base test case for indexing API tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser' + str(uuid.uuid4())[:8],
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-" + str(uuid.uuid4())[:8]
        )
        
        self.membership = Membership.objects.create(
            organization=self.org,
            user=self.user,
            role='admin',
            is_active=True
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            status="active"
        )
        
        # Create a default quota
        Quota.objects.create(
            org_id=self.org.id,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            limits={
                'max_sites': 10,
                'max_chatbots': 5,
                'daily_conversations': 1000,
                'concurrent_jobs': 5,
                'max_pages_per_site': 1000
            },
            usage={
                'sites_used': 1,
                'chatbots_used': 0,
                'chat_sessions_used': 0
            }
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
            documents_indexed=100,
            external_job_id=str(uuid.uuid4())
        )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertIn('count', data)
        self.assertIn('results', data)
        
        self.assertEqual(data['count'], 1)
        self.assertEqual(len(data['results']), 1)
        
        job_data = data['results'][0]
        self.assertEqual(job_data['site_domain'], 'https://example.com')
        self.assertEqual(job_data['status'], 'completed')
        self.assertEqual(job_data['documents_indexed'], 100)
        self.assertEqual(job_data['progress_percentage'], 100)
    
    def test_indexing_jobs_list_with_filters(self):
        """Test indexing jobs list with various filters"""
        # Create jobs with different statuses
        job1 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="completed",
            external_job_id=str(uuid.uuid4())
        )
        
        job2 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="failed",
            error_message="Test error",
            external_job_id=str(uuid.uuid4())
        )
        
        job3 = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            status="processing",
            external_job_id=str(uuid.uuid4())
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
    
    def test_indexing_jobs_list_pagination(self):
        """Test indexing jobs list pagination"""
        # Create multiple jobs
        for i in range(25):
            IndexingJob.objects.create(
                org_id=self.org.id,
                site_id=self.site.id,
                url=f"https://example{i}.com",
                status="completed",
                external_job_id=str(uuid.uuid4())
            )
        
        url = reverse('indexing-jobs-management')
        response = self.client.get(url, {'page': 1, 'page_size': 10})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 25)
        self.assertEqual(len(data['results']), 10)


class IndexingJobCreateAPITests(IndexingAPITestCase):
    """Comprehensive tests for indexing job creation API"""
    
    @patch('apps.indexing.services.IndexingService._call_indexing_service')
    def test_create_indexing_job_success(self, mock_call_service):
        """Test successful indexing job creation"""
        mock_call_service.return_value = {
            'task_id': 'task_123',
            'status': 'queued'
        }
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        response_data = response.json()
        self.assertIn('id', response_data)
        self.assertIn('external_job_id', response_data)
        self.assertEqual(response_data['status'], 'queued')
    
    def test_create_indexing_job_site_not_found(self):
        """Test indexing job creation with non-existent site"""
        url = reverse('create-indexing-job', kwargs={'site_id': uuid.uuid4()})
        url += f"?org_id={self.org.id}"
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_create_indexing_job_quota_exceeded(self):
        """Test indexing job creation when quota is exceeded"""
        # Trigger quota check by setting plan_tier to basic and limiting concurrent jobs
        self.org.plan_tier = 'basic'
        self.org.save()
        
        Quota.objects.filter(org_id=self.org.id).update(
            limits={
                'max_sites': 1,
                'max_chatbots': 1,
                'daily_conversations': 100,
                'concurrent_jobs': 0, # Exceeds limit
                'max_pages_per_site': 10
            }
        )
        
        url = reverse('create-indexing-job', kwargs={'site_id': self.site.id})
        url += f"?org_id={self.org.id}"
        data = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class IndexingServiceTests(TransactionTestCase):
    """Comprehensive tests for IndexingService"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser' + str(uuid.uuid4())[:8],
            email='test@example.com',
            password='testpass123'
        )
        
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-" + str(uuid.uuid4())[:8]
        )
        
        self.membership = Membership.objects.create(
            organization=self.org,
            user=self.user,
            role='admin',
            is_active=True
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            status="active"
        )
        
        Quota.objects.create(
            org_id=self.org.id,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            limits={'concurrent_jobs': 10},
            usage={'indexing_jobs_used': 0}
        )
    
    @patch('apps.indexing.services.IndexingService._call_indexing_service')
    def test_create_indexing_job_success(self, mock_call_service):
        """Test successful indexing job creation"""
        mock_call_service.return_value = {
            'task_id': 'task_123',
            'status': 'queued'
        }
        
        service = IndexingService()
        params = {
            'url': 'https://example.com',
            'max_pages': 100
        }
        
        with transaction.atomic():
            job = service.create_indexing_job(
                site=self.site,
                params=params,
                user_id=str(self.user.id)
            )
        
        self.assertIsNotNone(job)
        self.assertEqual(job.site_id, self.site.id)
        self.assertEqual(job.status, 'queued')
        mock_call_service.assert_called_once()

    def test_update_job_status_success(self):
        """Test successful job status update"""
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            url="https://example.com",
            external_job_id="job_123"
        )
        
        service = IndexingService()
        service.update_job_status(job.external_job_id, 'processing')
        job.refresh_from_db()
        self.assertEqual(job.status, 'processing')
        
        service.update_job_status(job.external_job_id, 'completed')
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')

    def test_build_callback_url(self):
        """Test callback URL building"""
        service = IndexingService()
        url = service._build_callback_url()
        self.assertIn('webhooks/indexing', url)
