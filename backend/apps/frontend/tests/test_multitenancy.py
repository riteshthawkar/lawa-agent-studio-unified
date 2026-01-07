"""
Tests for multi-tenancy enforcement in frontend views.

Tests ensure that:
- Users can only access their organization's data
- Cross-organization access is prevented
- Bulk operations respect organization boundaries
- Empty results returned for users without organizations
"""

import pytest
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.chatbot.models import Chatbot
import uuid

User = get_user_model()


@pytest.mark.django_db
class TestMultiTenancyEnforcement(TestCase):
    """Test multi-tenancy access control."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        # Create two organizations
        self.org1 = Organization.objects.create(
            name="Organization 1",
            subscription_tier="professional"
        )
        self.org2 = Organization.objects.create(
            name="Organization 2",
            subscription_tier="starter"
        )

        # Create users
        self.user1 = User.objects.create_user(
            email="user1@example.com",
            password="testpass123",
            first_name="User",
            last_name="One"
        )
        self.user2 = User.objects.create_user(
            email="user2@example.com",
            password="testpass123",
            first_name="User",
            last_name="Two"
        )
        self.user_no_org = User.objects.create_user(
            email="noorg@example.com",
            password="testpass123",
            first_name="No",
            last_name="Org"
        )

        # Create memberships
        Membership.objects.create(
            user=self.user1,
            organization=self.org1,
            role="admin",
            status="active"
        )
        Membership.objects.create(
            user=self.user2,
            organization=self.org2,
            role="member",
            status="active"
        )

        # Create test sites
        self.site1 = Site.objects.create(
            org_id=self.org1.id,
            domain="example1.com",
            status="active"
        )
        self.site2 = Site.objects.create(
            org_id=self.org2.id,
            domain="example2.com",
            status="active"
        )

        # Create test indexing jobs
        self.job1 = IndexingJob.objects.create(
            org_id=self.org1.id,
            site_id=self.site1.id,
            url="https://example1.com",
            status="completed"
        )
        self.job2 = IndexingJob.objects.create(
            org_id=self.org2.id,
            site_id=self.site2.id,
            url="https://example2.com",
            status="completed"
        )

        # Create test chatbots
        self.chatbot1 = Chatbot.objects.create(
            site_id=self.site1.id,
            name="Chatbot 1",
            status="active"
        )
        self.chatbot2 = Chatbot.objects.create(
            site_id=self.site2.id,
            name="Chatbot 2",
            status="active"
        )

    def test_dashboard_stats_filters_by_organization(self):
        """Test that dashboard stats only shows user's organization data."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/dashboard/stats/')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should see org1 data only
        assert data['sites']['total'] == 1
        assert data['indexing']['total_jobs'] == 1
        assert data['chatbots']['total'] == 1

    def test_dashboard_stats_different_organization(self):
        """Test that different users see different organization data."""
        # User 1 data
        self.client.force_authenticate(user=self.user1)
        response1 = self.client.get('/v1/frontend/dashboard/stats/')
        data1 = response1.json()

        # User 2 data
        self.client.force_authenticate(user=self.user2)
        response2 = self.client.get('/v1/frontend/dashboard/stats/')
        data2 = response2.json()

        # Both should succeed but see different data
        assert response1.status_code == status.HTTP_200_OK
        assert response2.status_code == status.HTTP_200_OK
        assert data1['sites']['total'] == 1
        assert data2['sites']['total'] == 1
        # But they're different sites
        assert data1['sites']['recent'][0]['id'] != data2['sites']['recent'][0]['id']

    def test_dashboard_stats_no_organization(self):
        """Test that users without organization see empty stats."""
        self.client.force_authenticate(user=self.user_no_org)
        response = self.client.get('/v1/frontend/dashboard/stats/')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should see empty stats
        assert data['sites']['total'] == 0
        assert data['indexing']['total_jobs'] == 0
        assert data['chatbots']['total'] == 0

    def test_sites_management_filters_by_organization(self):
        """Test that sites management only shows user's organization sites."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/sites/')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should see 1 site from org1
        assert data['count'] == 1
        assert data['results'][0]['id'] == str(self.site1.id)

    def test_indexing_jobs_filters_by_organization(self):
        """Test that indexing jobs are filtered by organization."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/indexing-jobs/')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should see 1 job from org1
        assert data['count'] == 1
        assert data['results'][0]['id'] == str(self.job1.id)

    def test_chatbots_management_filters_by_organization(self):
        """Test that chatbots are filtered by organization."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/chatbots/')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should see 1 chatbot from org1
        assert data['count'] == 1
        assert data['results'][0]['id'] == str(self.chatbot1.id)

    def test_bulk_actions_respects_organization(self):
        """Test that bulk actions only affect user's organization resources."""
        self.client.force_authenticate(user=self.user1)

        # Try to deactivate both chatbots (including one from another org)
        response = self.client.post('/v1/frontend/bulk-actions/', {
            'action_type': 'deactivate',
            'resource_type': 'chatbots',
            'resource_ids': [str(self.chatbot1.id), str(self.chatbot2.id)]
        }, format='json')

        assert response.status_code == status.HTTP_200_OK

        # Only chatbot1 should be deactivated
        self.chatbot1.refresh_from_db()
        self.chatbot2.refresh_from_db()
        assert self.chatbot1.status == 'inactive'
        assert self.chatbot2.status == 'active'  # Should not be affected

    def test_site_detail_cross_organization_access_denied(self):
        """Test that users cannot access sites from other organizations."""
        self.client.force_authenticate(user=self.user1)

        # Try to access org2's site
        response = self.client.get(f'/v1/frontend/sites/{self.site2.id}/')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_user_profile_filters_activity(self):
        """Test that user profile shows activity from user's organizations."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/user/profile/')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should show org1 activity only
        assert data['activity_summary']['sites_managed'] == 1
        assert data['activity_summary']['indexing_jobs_created'] == 1

    def test_pagination_with_organization_filter(self):
        """Test that pagination works correctly with organization filtering."""
        # Create more sites for org1
        for i in range(25):
            Site.objects.create(
                org_id=self.org1.id,
                domain=f"site{i}.example.com",
                status="active"
            )

        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/sites/?page=1&page_size=20')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should see paginated results from org1 only
        assert len(data['results']) == 20
        assert data['count'] == 26  # 1 original + 25 new
        assert data['next'] is not None

    def test_search_respects_organization(self):
        """Test that search results are filtered by organization."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/sites/?search=example')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should find site1 but not site2
        assert data['count'] == 1
        assert data['results'][0]['domain'] == 'example1.com'

    def test_ordering_with_organization_filter(self):
        """Test that ordering works correctly with organization filtering."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/v1/frontend/sites/?ordering=-created_at')

        assert response.status_code == status.HTTP_200_OK
        # Should not error and should only show org1 sites
        assert response.json()['count'] == 1
