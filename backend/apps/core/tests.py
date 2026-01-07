from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot

User = get_user_model()


class CoreTestCase(TestCase):
    """Test core functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            email='test@example.com',
            username='testuser',
            name='Test User'
        )
        
        self.org = Organization.objects.create(
            name='Test Organization',
            slug='test-org'
        )
        
        self.membership = Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        
        self.site = Site.objects.create(
            org_id=self.org.id,
            domain='https://test.com',
            status='active'
        )
        
        self.chatbot = Chatbot.objects.create(
            org_id=self.org.id,
            site_id=self.site.id,
            name='Test Chatbot'
        )
    
    def test_user_creation(self):
        """Test user creation"""
        self.assertEqual(self.user.email, 'test@example.com')
        self.assertEqual(self.user.name, 'Test User')
    
    def test_organization_creation(self):
        """Test organization creation"""
        self.assertEqual(self.org.name, 'Test Organization')
        self.assertEqual(self.org.slug, 'test-org')
    
    def test_membership_creation(self):
        """Test membership creation"""
        self.assertEqual(self.membership.user, self.user)
        self.assertEqual(self.membership.organization, self.org)
        self.assertEqual(self.membership.role, 'owner')
    
    def test_site_creation(self):
        """Test site creation"""
        self.assertEqual(self.site.domain, 'https://test.com')
        self.assertEqual(self.site.org_id, self.org.id)
        self.assertEqual(self.site.status, 'active')
    
    def test_chatbot_creation(self):
        """Test chatbot creation"""
        self.assertEqual(self.chatbot.name, 'Test Chatbot')
        self.assertEqual(self.chatbot.org_id, self.org.id)
        self.assertEqual(self.chatbot.site_id, self.site.id)
    
    def test_site_namespace(self):
        """Test site namespace generation"""
        expected_namespace = f"tenant_{self.org.id}__site_{self.site.id}"
        self.assertEqual(self.site.get_namespace(), expected_namespace)
