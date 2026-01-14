"""
Comprehensive tests for Sites services and models.

These tests cover:
- SiteVerificationService
- Site model methods
- ExcludedURLPattern matching
"""
import pytest
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4

from apps.sites.models import Site, ExcludedURLPattern
from apps.sites.services import SiteVerificationService
from apps.organizations.models import Organization


class SiteModelTests(TestCase):
    """Tests for Site model methods"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id,
            status='active'
        )
    
    def test_get_namespace_with_active_namespace(self):
        """Test get_namespace returns active_namespace when set"""
        namespace = f"site_{self.site.id}_1234567890"
        self.site.active_namespace = namespace
        self.site.save()
        
        result = self.site.get_namespace()
        
        self.assertEqual(result, namespace)
    
    def test_get_namespace_fallback(self):
        """Test get_namespace fallback when active_namespace is None"""
        self.site.active_namespace = None
        self.site.save()
        
        result = self.site.get_namespace()
        
        self.assertEqual(result, f"site_{self.site.id}")
    
    def test_get_excluded_patterns(self):
        """Test getting excluded patterns for site"""
        # Create some patterns
        ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            org_id=self.org.id,
            pattern="/admin/*",
            pattern_type="prefix",
            is_active=True
        )
        ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            org_id=self.org.id,
            pattern="/login",
            pattern_type="exact",
            is_active=True
        )
        ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            org_id=self.org.id,
            pattern="/old/*",
            pattern_type="prefix",
            is_active=False  # Inactive
        )
        
        patterns = self.site.get_excluded_patterns()
        
        self.assertEqual(len(patterns), 2)
        self.assertIn("/admin/*", patterns)
        self.assertIn("/login", patterns)
        self.assertNotIn("/old/*", patterns)
    
    def test_site_str(self):
        """Test Site string representation"""
        self.assertEqual(str(self.site), "https://example.com")


class ExcludedURLPatternTests(TestCase):
    """Tests for ExcludedURLPattern model"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id
        )
    
    def test_matches_url_exact(self):
        """Test exact URL matching"""
        pattern = ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            pattern="https://example.com/login",
            pattern_type="exact"
        )
        
        self.assertTrue(pattern.matches_url("https://example.com/login"))
        self.assertFalse(pattern.matches_url("https://example.com/login/"))
        self.assertFalse(pattern.matches_url("https://example.com/other"))
    
    def test_matches_url_prefix(self):
        """Test prefix URL matching"""
        pattern = ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            pattern="https://example.com/admin",
            pattern_type="prefix"
        )
        
        self.assertTrue(pattern.matches_url("https://example.com/admin"))
        self.assertTrue(pattern.matches_url("https://example.com/admin/settings"))
        self.assertTrue(pattern.matches_url("https://example.com/admin/users/123"))
        self.assertFalse(pattern.matches_url("https://example.com/user/admin"))
    
    def test_matches_url_suffix(self):
        """Test suffix URL matching"""
        pattern = ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            pattern=".pdf",
            pattern_type="suffix"
        )
        
        self.assertTrue(pattern.matches_url("https://example.com/doc.pdf"))
        self.assertTrue(pattern.matches_url("https://example.com/files/report.pdf"))
        self.assertFalse(pattern.matches_url("https://example.com/pdf-reader"))
    
    def test_matches_url_contains(self):
        """Test contains URL matching"""
        pattern = ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            pattern="utm_",
            pattern_type="contains"
        )
        
        self.assertTrue(pattern.matches_url("https://example.com/page?utm_source=google"))
        self.assertTrue(pattern.matches_url("https://example.com/page?foo=bar&utm_medium=cpc"))
        self.assertFalse(pattern.matches_url("https://example.com/page?source=google"))
    
    def test_matches_url_regex(self):
        """Test regex URL matching"""
        pattern = ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            pattern=r".*\.(jpg|png|gif)$",
            pattern_type="regex"
        )
        
        self.assertTrue(pattern.matches_url("https://example.com/image.jpg"))
        self.assertTrue(pattern.matches_url("https://example.com/photo.png"))
        self.assertTrue(pattern.matches_url("https://example.com/animation.gif"))
        self.assertFalse(pattern.matches_url("https://example.com/image.webp"))
    
    def test_matches_url_invalid_regex(self):
        """Test that invalid regex doesn't crash"""
        pattern = ExcludedURLPattern.objects.create(
            site_id=self.site.id,
            pattern="[invalid(regex",
            pattern_type="regex"
        )
        
        # Should return False for invalid regex, not crash
        result = pattern.matches_url("https://example.com/test")
        self.assertFalse(result)
    
    def test_validate_pattern_valid_regex(self):
        """Test pattern validation for valid regex"""
        pattern = ExcludedURLPattern(
            site_id=self.site.id,
            pattern=r".*\.pdf$",
            pattern_type="regex"
        )
        
        is_valid, error = pattern.validate_pattern()
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_pattern_invalid_regex(self):
        """Test pattern validation for invalid regex"""
        pattern = ExcludedURLPattern(
            site_id=self.site.id,
            pattern="[invalid(regex",
            pattern_type="regex"
        )
        
        is_valid, error = pattern.validate_pattern()
        
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)


class SiteVerificationServiceTests(TestCase):
    """Tests for SiteVerificationService"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            slug="test-org"
        )
        self.site = Site.objects.create(
            name="Test Site",
            domain="https://example.com",
            org_id=self.org.id
        )
        self.service = SiteVerificationService()
    
    def test_verify_site_mvp_mode(self):
        """Test that verify_site returns True in MVP mode"""
        # Currently MVP mode skips verification
        result = self.service.verify_site(self.site)
        self.assertTrue(result)
    
    @patch('dns.resolver.resolve')
    def test_verify_dns_record_success(self, mock_resolve):
        """Test successful DNS verification"""
        mock_record = MagicMock()
        mock_record.__str__ = MagicMock(return_value='"test-token-123"')
        mock_resolve.return_value = [mock_record]
        
        self.site.verification_token = "test-token-123"
        result = self.service.verify_dns_record(self.site)
        
        self.assertTrue(result)
    
    @patch('dns.resolver.resolve')
    def test_verify_dns_record_wrong_token(self, mock_resolve):
        """Test DNS verification with wrong token"""
        mock_record = MagicMock()
        mock_record.__str__ = MagicMock(return_value='"wrong-token"')
        mock_resolve.return_value = [mock_record]
        
        result = self.service.verify_dns_record(self.site)
        
        self.assertFalse(result)
    
    @patch('dns.resolver.resolve')
    def test_verify_dns_record_nxdomain(self, mock_resolve):
        """Test DNS verification when domain doesn't exist"""
        import dns.resolver
        mock_resolve.side_effect = dns.resolver.NXDOMAIN()
        
        result = self.service.verify_dns_record(self.site)
        
        self.assertFalse(result)
    
    @patch('requests.get')
    def test_verify_file_upload_success(self, mock_get):
        """Test successful file upload verification"""
        mock_response = MagicMock()
        mock_response.text = "test-token-123"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        self.site.verification_token = "test-token-123"
        result = self.service.verify_file_upload(self.site)
        
        self.assertTrue(result)
    
    @patch('requests.get')
    def test_verify_file_upload_wrong_content(self, mock_get):
        """Test file upload verification with wrong content"""
        mock_response = MagicMock()
        mock_response.text = "wrong-content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        result = self.service.verify_file_upload(self.site)
        
        self.assertFalse(result)
    
    @patch('requests.get')
    def test_verify_file_upload_timeout(self, mock_get):
        """Test file upload verification timeout"""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()
        
        result = self.service.verify_file_upload(self.site)
        
        self.assertFalse(result)
    
    def test_mark_site_verified(self):
        """Test marking site as verified"""
        self.site.status = 'inactive'
        self.site.save()
        
        self.service.mark_site_verified(self.site)
        
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, 'active')
        self.assertEqual(self.site.status, 'active')
    
    def test_mark_site_failed(self):
        """Test marking site verification as failed"""
        self.site.status = 'inactive'
        self.site.save()
        
        self.service.mark_site_failed(self.site, "Verification timeout")
        
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, 'inactive')
