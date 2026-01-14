"""
Comprehensive tests for namespace functionality.

These tests ensure that the namespace logic for sites works correctly,
preventing issues like the "no results found" bug caused by namespace
format mismatches between indexing and retrieval.
"""
import uuid
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch, MagicMock
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.organizations.models import Organization


class SiteNamespaceTests(TestCase):
    """Tests for Site.get_namespace() method"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org"
        )
        self.site = Site.objects.create(
            domain="https://example.com",
            name="Example Site",
            org_id=self.org.id,
            status='active'
        )
    
    def test_get_namespace_returns_active_namespace_when_set(self):
        """Test that get_namespace() returns active_namespace when it's set"""
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        self.assertEqual(self.site.get_namespace(), expected_namespace)
    
    def test_get_namespace_returns_fallback_when_active_namespace_empty(self):
        """Test that get_namespace() returns fallback format when active_namespace is empty"""
        self.site.active_namespace = ""
        self.site.save()
        
        expected_fallback = f"site_{self.site.id}"
        self.assertEqual(self.site.get_namespace(), expected_fallback)
    
    def test_get_namespace_returns_fallback_when_active_namespace_null(self):
        """Test that get_namespace() returns fallback format when active_namespace is None"""
        self.site.active_namespace = None
        self.site.save()
        
        expected_fallback = f"site_{self.site.id}"
        self.assertEqual(self.site.get_namespace(), expected_fallback)
    
    def test_namespace_format_matches_indexing_format(self):
        """Test that namespace format matches the format used by IndexingService"""
        # Simulate what IndexingService creates
        timestamp = int(timezone.now().timestamp())
        indexer_namespace = f"site_{self.site.id}_{timestamp}"
        
        # Set this as the active namespace
        self.site.active_namespace = indexer_namespace
        self.site.save()
        
        # Verify get_namespace returns the same format
        self.assertEqual(self.site.get_namespace(), indexer_namespace)
        self.assertIn(str(self.site.id), self.site.get_namespace())
        self.assertIn("_", self.site.get_namespace())  # Should have timestamp separator


class NamespaceUpdateOnWebhookTests(TestCase):
    """Tests for namespace updates when webhook is received"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-webhook"
        )
        self.site = Site.objects.create(
            domain="https://webhook-test.com",
            name="Webhook Test Site",
            org_id=self.org.id,
            status='active'
        )
        self.job = IndexingJob.objects.create(
            site_id=self.site.id,
            org_id=self.org.id,
            url="https://webhook-test.com",
            status='processing',
            external_job_id='test-job-123',
            target_namespace=f"site_{self.site.id}_1234567890"
        )
    
    def test_site_namespace_updated_on_job_completion(self):
        """Test that site.active_namespace is updated when indexing job completes"""
        from apps.indexing.services import IndexingService
        
        # Initial state - no active namespace
        self.assertIsNone(self.site.active_namespace)
        
        # Simulate job completion via IndexingService
        service = IndexingService()
        
        with patch.object(service, '_delete_vectors_by_urls', return_value=0):
            job = service.update_job_status(
                job_id=self.job.external_job_id,
                status='completed',
                progress_data={'urls_collected': 10, 'urls_processed': 10, 'documents_indexed': 50}
            )
        
        # Refresh site from DB
        self.site.refresh_from_db()
        
        # Verify active_namespace was set
        self.assertEqual(self.site.active_namespace, self.job.target_namespace)
    
    def test_site_namespace_not_updated_on_job_failure(self):
        """Test that site.active_namespace is NOT updated when job fails"""
        from apps.indexing.services import IndexingService
        
        # Set an initial namespace
        old_namespace = "site_old_namespace"
        self.site.active_namespace = old_namespace
        self.site.save()
        
        # Simulate job failure
        service = IndexingService()
        job = service.update_job_status(
            job_id=self.job.external_job_id,
            status='failed',
            error_message='Test failure'
        )
        
        # Refresh site from DB
        self.site.refresh_from_db()
        
        # Verify active_namespace was NOT changed
        self.assertEqual(self.site.active_namespace, old_namespace)
    
    def test_job_without_target_namespace_does_not_update_site(self):
        """Test that jobs without target_namespace don't update site"""
        # Create job without target_namespace
        job_no_ns = IndexingJob.objects.create(
            site_id=self.site.id,
            org_id=self.org.id,
            url="https://webhook-test.com",
            status='processing',
            external_job_id='test-job-no-ns',
            target_namespace=""  # No namespace (empty string, not Null)
        )
        
        from apps.indexing.services import IndexingService
        
        # Set an initial namespace
        old_namespace = "site_keep_this"
        self.site.active_namespace = old_namespace
        self.site.save()
        
        # Simulate job completion
        service = IndexingService()
        with patch.object(service, '_delete_vectors_by_urls', return_value=0):
            service.update_job_status(
                job_id=job_no_ns.external_job_id,
                status='completed'
            )
        
        # Refresh site from DB
        self.site.refresh_from_db()
        
        # Verify active_namespace was NOT changed (stayed as old_namespace)
        self.assertEqual(self.site.active_namespace, old_namespace)


class NamespaceConsistencyTests(TestCase):
    """Tests to ensure namespace consistency across the application"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-consistency"
        )
        self.site = Site.objects.create(
            domain="https://consistency-test.com",
            name="Consistency Test Site",
            org_id=self.org.id,
            status='active',
            active_namespace=None
        )
    
    def test_serializer_exposes_namespace(self):
        """Test that Site serializer exposes the namespace correctly"""
        from apps.sites.serializers import SiteSerializer
        
        # Set namespace
        expected_namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = expected_namespace
        self.site.save()
        
        serializer = SiteSerializer(self.site)
        data = serializer.data
        
        self.assertIn('namespace', data)
        self.assertEqual(data['namespace'], expected_namespace)
    
    def test_serializer_exposes_fallback_namespace(self):
        """Test that Site serializer exposes fallback namespace when active_namespace is empty"""
        from apps.sites.serializers import SiteSerializer
        
        self.site.active_namespace = None
        self.site.save()
        
        serializer = SiteSerializer(self.site)
        data = serializer.data
        
        expected_fallback = f"site_{self.site.id}"
        self.assertIn('namespace', data)
        self.assertEqual(data['namespace'], expected_fallback)


class IndexingJobNamespaceTests(TestCase):
    """Tests for IndexingJob namespace-related functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org-job"
        )
        self.site = Site.objects.create(
            domain="https://job-test.com",
            name="Job Test Site",
            org_id=self.org.id,
            status='active'
        )
    
    def test_indexing_service_creates_timestamped_namespace(self):
        """Test that IndexingService creates namespace with timestamp"""
        from apps.indexing.services import IndexingService
        from unittest.mock import patch
        
        service = IndexingService()
        
        # Mock the external service call
        with patch.object(service, '_call_indexing_service') as mock_call:
            mock_call.return_value = {'task_id': 'test-task-123', 'status': 'queued'}
            
            job = service.create_indexing_job(
                site=self.site,
                params={'url': 'https://job-test.com', 'max_pages': 10},
                user_id='test-user-123'
            )
        
        # Verify namespace format
        self.assertIsNotNone(job.target_namespace)
        self.assertIn(str(self.site.id), job.target_namespace)
        # Should have format: site_{uuid}_{timestamp}
        parts = job.target_namespace.split('_')
        self.assertEqual(parts[0], 'site')
        # Last part should be numeric timestamp
        self.assertTrue(parts[-1].isdigit())
    
    def test_append_mode_uses_existing_namespace(self):
        """Test that append mode reuses the existing active_namespace"""
        from apps.indexing.services import IndexingService
        from unittest.mock import patch
        
        # Set existing namespace
        existing_namespace = f"site_{self.site.id}_existing123"
        self.site.active_namespace = existing_namespace
        self.site.save()
        
        service = IndexingService()
        
        # Mock the external service call
        with patch.object(service, '_call_indexing_service') as mock_call:
            mock_call.return_value = {'task_id': 'test-task-456', 'status': 'queued'}
            
            job = service.create_indexing_job(
                site=self.site,
                params={'url': 'https://job-test.com', 'max_pages': 10},
                user_id='test-user-123',
                append_mode=True
            )
        
        # Should use existing namespace, not create new one
        self.assertEqual(job.target_namespace, existing_namespace)
