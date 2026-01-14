"""
Comprehensive tests for webhook functionality.

These tests ensure that indexing webhooks correctly update site namespaces,
handle errors gracefully, and maintain data integrity.
"""
import pytest
import json
import hmac
import hashlib
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock
import uuid

from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.organizations.models import Organization
from apps.webhooks.models import WebhookEvent, AuditLog

@pytest.mark.django_db
class WebhookBasicTests(APITestCase):
    """Basic tests for webhook endpoint"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Organization",
            slug=f"test-org-webhook-{uuid.uuid4().hex[:8]}"
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
            external_job_id='webhook-test-job-123',
            target_namespace=f"site_{self.site.id}_1234567890",
            callback_url='http://localhost:8000/v1/webhooks/indexing/'
        )
        self.webhook_url = reverse('indexing-webhook')

    def _get_signed_payload(self, payload, secret="test-secret"):
        """Helper to sign payload"""
        body = json.dumps(payload).encode()
        signature = hmac.new(
            secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        return body, signature

    @override_settings(WEBHOOK_SIGNING_SECRET="test-secret")
    def test_webhook_updates_job_status_to_completed(self):
        """Test that webhook successfully updates job status to completed"""
        payload = {
            'external_job_id': self.job.external_job_id,
            'task_id': 'task-123',
            'status': 'completed',
            'result': {
                'stats': {
                    'urls_collected': 10,
                    'urls_processed': 10,
                    'documents_indexed': 50
                }
            }
        }
        
        body, signature = self._get_signed_payload(payload)
        
        with patch('apps.indexing.services.IndexingService._delete_vectors_by_urls', return_value=0):
            response = self.client.post(
                self.webhook_url,
                data=body,
                HTTP_X_SIGNATURE=signature,
                content_type='application/json'
            )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify job was updated
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'completed')

    @override_settings(WEBHOOK_SIGNING_SECRET="test-secret")
    def test_webhook_updates_site_active_namespace_on_completion(self):
        """Test that webhook updates site.active_namespace when job completes"""
        self.site.active_namespace = None
        self.site.save()
        
        payload = {
            'external_job_id': self.job.external_job_id,
            'task_id': 'task-123',
            'status': 'completed',
            'result': {
                'stats': {
                    'urls_collected': 10,
                    'urls_processed': 10,
                    'documents_indexed': 50
                }
            }
        }
        
        body, signature = self._get_signed_payload(payload)
        
        with patch('apps.indexing.services.IndexingService._delete_vectors_by_urls', return_value=0):
            response = self.client.post(
                self.webhook_url,
                data=body,
                HTTP_X_SIGNATURE=signature,
                content_type='application/json'
            )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.active_namespace)

    @override_settings(WEBHOOK_SIGNING_SECRET=None)
    def test_webhook_requires_external_job_id(self):
        """Test that webhook requires external_job_id"""
        payload = {
            'status': 'completed'
        }
        response = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(WEBHOOK_SIGNING_SECRET=None)
    def test_webhook_requires_status(self):
        """Test that webhook requires status"""
        payload = {
            'external_job_id': self.job.external_job_id
        }
        response = self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

@pytest.mark.django_db
class WebhookCallbackURLTests(TestCase):
    """Tests for callback URL generation and storage"""
    
    def setUp(self):
        self.org = Organization.objects.create(name="Test")
        self.site = Site.objects.create(domain="https://test.com", org_id=self.org.id)
        
    def test_callback_url_fallback(self):
        from apps.indexing.services import IndexingService
        service = IndexingService()
        callback_url = service._build_callback_url()
        self.assertIn('/v1/webhooks/indexing/', callback_url)

    @patch('requests.post')
    def test_job_stores_callback_url(self, mock_post):
        from apps.indexing.services import IndexingService
        service = IndexingService()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'task_id': 'test-task'}
        mock_post.return_value = mock_response
        
        from django.db import transaction
        with transaction.atomic():
            job = service.create_indexing_job(
                self.site,
                {'url': 'https://test.com', 'max_pages': 10},
                user_id=str(uuid.uuid4())
            )
        
        self.assertIsNotNone(job.callback_url)
        self.assertIn('/v1/webhooks/indexing/', job.callback_url)
