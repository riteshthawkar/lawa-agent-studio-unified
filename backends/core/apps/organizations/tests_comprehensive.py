"""
Comprehensive tests for Organizations endpoints.

These tests cover multi-tenancy and access control:
- Organization CRUD
- Membership management
- Cross-organization isolation
"""
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from apps.organizations.models import Organization, Membership
from apps.sites.models import Site

User = get_user_model()


class OrganizationTestCase(APITestCase):
    """Base test case for organization tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='org_test_user',
            email='org_test@example.com',
            password='TestPassword123!',
            is_email_verified=True
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org"
        )
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        self.client.force_authenticate(user=self.user)


class OrganizationCRUDTests(OrganizationTestCase):
    """Tests for organization CRUD operations"""
    
    def test_list_organizations(self):
        """Test listing user's organizations"""
        url = reverse('organization-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        orgs = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(orgs), 1)
    
    def test_create_organization(self):
        """Test creating a new organization"""
        url = reverse('organization-list')
        payload = {
            'name': 'New Organization',
            'slug': 'new-org'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Organization')
        
        # User should be added as owner
        new_org = Organization.objects.get(slug='new-org')
        membership = Membership.objects.get(
            user=self.user,
            organization=new_org
        )
        self.assertEqual(membership.role, 'owner')
    
    def test_create_organization_auto_slug(self):
        """Test that slug is auto-generated if not provided"""
        url = reverse('organization-list')
        payload = {
            'name': 'Auto Slug Organization'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.data['slug'])
    
    def test_get_organization_detail(self):
        """Test getting organization details"""
        url = reverse('organization-detail', kwargs={'pk': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], self.org.name)
    
    def test_update_organization(self):
        """Test updating organization"""
        url = reverse('organization-detail', kwargs={'pk': self.org.id})
        payload = {
            'name': 'Updated Organization Name'
        }
        
        response = self.client.patch(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, 'Updated Organization Name')
    
    def test_delete_organization(self):
        """Test deleting organization (soft delete)"""
        url = reverse('organization-detail', kwargs={'pk': self.org.id})
        response = self.client.delete(url)
        
        # Should succeed (200 or 204)
        self.assertIn(response.status_code, [
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT
        ])


class MembershipManagementTests(OrganizationTestCase):
    """Tests for membership management"""
    
    def test_list_members(self):
        """Test listing organization members"""
        url = reverse('membership-list', kwargs={'org_id': self.org.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        members = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(members), 1)
    
    def test_add_member(self):
        """Test adding a member to organization"""
        # Create new user to add
        new_user = User.objects.create_user(
            username='new_member_user',
            email='new_member@example.com',
            password='NewMember123!'
        )
        
        url = reverse('membership-list', kwargs={'org_id': self.org.id})
        payload = {
            'user_id': str(new_user.id),
            'role': 'member'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify membership created
        self.assertTrue(
            Membership.objects.filter(
                user=new_user,
                organization=self.org
            ).exists()
        )
    
    def test_add_member_requires_admin(self):
        """Test that adding members requires admin/owner role"""
        # Create a regular member
        member_user = User.objects.create_user(
            username='regular_member_user',
            email='regular_member@example.com',
            password='Member123!'
        )
        Membership.objects.create(
            user=member_user,
            organization=self.org,
            role='member'  # Not admin or owner
        )
        
        # Authenticate as regular member
        self.client.force_authenticate(user=member_user)
        
        # Try to add another member
        new_user = User.objects.create_user(
            username='another_user',
            email='another_user@example.com',
            password='Another123!'
        )
        
        url = reverse('membership-list', kwargs={'org_id': self.org.id})
        payload = {
            'user_email': new_user.email,
            'role': 'member'
        }
        
        response = self.client.post(url, payload, format='json')
        
        # Should be forbidden
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_remove_member(self):
        """Test removing a member from organization"""
        # Add a member to remove
        member_user = User.objects.create_user(
            username='to_remove_user',
            email='to_remove@example.com',
            password='Remove123!'
        )
        membership = Membership.objects.create(
            user=member_user,
            organization=self.org,
            role='member'
        )
        
        url = reverse('membership-detail', kwargs={
            'org_id': self.org.id,
            'pk': membership.id
        })
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify membership removed
        self.assertFalse(
            Membership.objects.filter(id=membership.id).exists()
        )
    
    def test_cannot_remove_last_owner(self):
        """Test that the last owner cannot be removed"""
        # Try to remove self (only owner)
        membership = Membership.objects.get(
            user=self.user,
            organization=self.org
        )
        
        url = reverse('membership-detail', kwargs={
            'org_id': self.org.id,
            'pk': membership.id
        })
        response = self.client.delete(url)
        
        # Should fail - can't remove last owner
        self.assertIn(response.status_code, [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_403_FORBIDDEN
        ])


class OrganizationIsolationTests(APITestCase):
    """Tests for cross-organization data isolation"""
    
    def setUp(self):
        """Set up test data with multiple organizations"""
        # User 1 with Org 1
        self.user1 = User.objects.create_user(
            username='user1_org',
            email='user1@example.com',
            password='User1Pass123!',
            is_email_verified=True
        )
        self.org1 = Organization.objects.create(
            name="Organization 1",
            slug="org-1"
        )
        Membership.objects.create(
            user=self.user1,
            organization=self.org1,
            role='owner'
        )
        
        # User 2 with Org 2
        self.user2 = User.objects.create_user(
            username='user2_org',
            email='user2@example.com',
            password='User2Pass123!',
            is_email_verified=True
        )
        self.org2 = Organization.objects.create(
            name="Organization 2",
            slug="org-2"
        )
        Membership.objects.create(
            user=self.user2,
            organization=self.org2,
            role='owner'
        )
        
        # Create sites for each org
        self.site1 = Site.objects.create(
            domain="https://org1-site.com",
            name="Org 1 Site",
            org_id=self.org1.id,
            status='active'
        )
        self.site2 = Site.objects.create(
            domain="https://org2-site.com",
            name="Org 2 Site",
            org_id=self.org2.id,
            status='active'
        )
    
    def test_user_cannot_see_other_org(self):
        """Test that user cannot see other organizations"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('organization-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        orgs = response.data if isinstance(response.data, list) else response.data.get('results', [])
        org_ids = [str(o.get('id')) for o in orgs]
        
        # Should see own org
        self.assertIn(str(self.org1.id), org_ids)
        # Should NOT see other org
        self.assertNotIn(str(self.org2.id), org_ids)
    
    def test_user_cannot_access_other_org_detail(self):
        """Test that user cannot access other org's details"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('organization-detail', kwargs={'pk': self.org2.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_user_cannot_see_other_org_sites(self):
        """Test that user cannot see sites from other organizations"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('site-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        sites = response.data if isinstance(response.data, list) else response.data.get('results', [])
        domains = [s.get('domain', '') for s in sites]
        
        # Should see own site
        self.assertIn(self.site1.domain, domains)
        # Should NOT see other org's site
        self.assertNotIn(self.site2.domain, domains)
    
    def test_user_cannot_access_other_org_site(self):
        """Test that user cannot access specific site from other org"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('site-detail', kwargs={'pk': self.site2.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_user_cannot_update_other_org(self):
        """Test that user cannot update other organization"""
        self.client.force_authenticate(user=self.user1)
        
        url = reverse('organization-detail', kwargs={'pk': self.org2.id})
        payload = {
            'name': 'Hacked Name'
        }
        
        response = self.client.patch(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # Verify org2 unchanged
        self.org2.refresh_from_db()
        self.assertEqual(self.org2.name, "Organization 2")
    
    def test_user_cannot_add_member_to_other_org(self):
        """Test that user cannot add member to other organization"""
        self.client.force_authenticate(user=self.user1)
        
        new_user = User.objects.create_user(
            username='new_user_org2',
            email='new_user@example.com',
            password='NewUser123!'
        )
        
        url = reverse('membership-list', kwargs={'org_id': self.org2.id})
        payload = {
            'user_email': new_user.email,
            'role': 'member'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertIn(response.status_code, [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND
        ])


class UserOrganizationsTests(OrganizationTestCase):
    """Tests for user organizations endpoint"""
    
    def test_get_user_organizations(self):
        """Test getting current user's organizations"""
        url = reverse('user-organizations')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        orgs = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(orgs), 1)
    
    def test_user_multiple_organizations(self):
        """Test user with multiple organizations"""
        # Add second org
        org2 = Organization.objects.create(
            name="Second Org",
            slug="second-org"
        )
        Membership.objects.create(
            user=self.user,
            organization=org2,
            role='member'
        )
        
        url = reverse('user-organizations')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        orgs = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(orgs), 2)
