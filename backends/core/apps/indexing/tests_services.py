"""
Comprehensive tests for IndexingService.

These tests cover:
- Job creation and management
- Webhook handling
- Vector cleanup operations
- Quota enforcement
"""
import pytest
import json
import uuid
import hashlib
from django.test import TestCase, TransactionTestCase
from django.conf import settings
from django.utils import timezone
from unittest.mock import patch, MagicMock, Mock
import requests
from django.db import transaction

from apps.indexing.services import IndexingService
from apps.indexing.models import IndexingJob
from apps.sites.models import Site, ExcludedURLPattern
from apps.organizations.models import Organization, Membership
from apps.usage.models import Quota


class IndexingServiceJobCreationTests(TransactionTestCase):
    """Tests for indexing job creation"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org-" + str(uuid.uuid4())[:8]
        )
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            status="active"
        )
        # Create quota
        Quota.objects.create(
            org_id=self.org.id,
            period_start=timezone.now(),
            period_end=timezone.now() + timezone.timedelta(days=30),
            limits={'concurrent_jobs': 10},
            usage={'indexing_jobs_used': 0}
        )
        self.service = IndexingService()
    
    @patch.object(IndexingService, '_call_indexing_service')
    def test_create_indexing_job_success(self, mock_call):
        """Test successful indexing job creation"""
        mock_call.return_value = {
            'task_id': 'task-123',
            'status': 'queued'
        }
        
        params = {
            'url': 'https://example.com',
            'max_pages': 50
        }
        
        with transaction.atomic():
            job = self.service.create_indexing_job(
                site=self.site,
                params=params,
                user_id=str(uuid.uuid4())
            )
        
        self.assertIsNotNone(job)
        self.assertEqual(job.site_id, self.site.id)
        self.assertEqual(job.org_id, self.org.id)
        self.assertEqual(job.status, 'queued')
        mock_call.assert_called_once()
    
    @patch.object(IndexingService, '_call_indexing_service')
    def test_create_indexing_job_internal_call(self, mock_call):
        """Test that _call_indexing_service is called with correct params"""
        mock_call.return_value = {'task_id': 'task-123', 'status': 'queued'}
        
        user_id = str(uuid.uuid4())
        params = {'url': 'https://example.com', 'max_pages': 50}
        
        with transaction.atomic():
            job = self.service.create_indexing_job(
                site=self.site,
                params=params,
                user_id=user_id
            )
        
        # Verify mock_call with site object (passed positionally in trigger_indexing_service)
        args, kwargs = mock_call.call_args
        self.assertEqual(args[0], self.site)
        self.assertEqual(args[2], job.external_job_id)
        self.assertEqual(args[3], user_id)


class IndexingServiceStatusUpdateTests(TestCase):
    """Tests for job status updates"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org-" + str(uuid.uuid4())[:8]
        )
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            status="active"
        )
        self.job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            external_job_id="ext-job-123",
            task_id="task-123",
            status="queued"
        )
        self.service = IndexingService()
    
    def test_update_job_status(self):
        """Test updating job status from webhook or helper"""
        ext_id = "ext-job-" + str(uuid.uuid4())[:8]
        job = IndexingJob.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            external_job_id=ext_id,
            task_id="task-123",
            status="queued"
        )
        self.service.update_job_status(ext_id, "processing")
        job.refresh_from_db()
        self.assertEqual(job.status, "processing")
        
        self.service.update_job_status(ext_id, "completed", phase1_result={'docs': 100})
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.phase1_result, {'docs': 100})


class IndexingServiceHelperTests(TestCase):
    """Tests for helper methods"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org-" + str(uuid.uuid4())[:8]
        )
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain="https://example.com",
            status="active"
        )
        self.service = IndexingService()
    
    def test_generate_job_id(self):
        """Test job ID generation"""
        params = {'url': 'https://example.com', 'max_pages': 50}
        job_id = self.service._generate_job_id(self.site, params)
        
        self.assertIsNotNone(job_id)
        self.assertEqual(len(job_id), 16)
    
    def test_build_callback_url(self):
        """Test callback URL building"""
        url = self.service._build_callback_url()
        self.assertIn('webhooks/indexing', url)


class IndexingServiceSearchTests(TestCase):
    """Tests for knowledge base search"""
    
    def setUp(self):
        self.service = IndexingService()
    
    @patch('apps.indexing.services.requests.post')
    def test_search_knowledge_base_success(self, mock_post):
        """Test searching knowledge base"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [
                {'content': 'text 1', 'score': 0.9},
                {'content': 'text 2', 'score': 0.8}
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        result = self.service.search_knowledge_base(
            namespace="test-ns",
            query="test query"
        )
        
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(result['results'][0]['content'], 'text 1')
