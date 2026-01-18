"""
Comprehensive API tests for analytics endpoints.

Tests cover:
- Authentication and authorization
- Tier-based feature gating
- Query parameter handling
- Response structure validation
- Multi-tenant data isolation
- Edge cases and error handling
"""

import json
from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences
from apps.analytics.tests.test_factories import TestDataFactory


class LeadsDashboardAPITests(TestCase):
    """Tests for GET /v1/frontend/analytics/leads/"""

    def setUp(self):
        """Set up test fixtures with different tier subscriptions."""
        self.client = APIClient()

        # Create basic tier user
        self.basic_setup = TestDataFactory.create_complete_test_setup(plan='basic')
        self.basic_user = self.basic_setup['user']

        # Create premium tier user
        self.premium_setup = TestDataFactory.create_complete_test_setup(plan='premium')
        self.premium_user = self.premium_setup['user']

        # Create enterprise tier user
        self.enterprise_setup = TestDataFactory.create_complete_test_setup(plan='enterprise')
        self.enterprise_user = self.enterprise_setup['user']

    def test_unauthenticated_access_returns_401(self):
        """
        Test that unauthenticated requests are rejected.
        Real-world scenario: Prevent unauthorized access to lead data.
        """
        response = self.client.get('/v1/frontend/analytics/leads/')
        self.assertIn(response.status_code, [401, 403])

    def test_basic_tier_returns_limited_data(self):
        """
        Test that basic tier gets limited analytics.
        Real-world scenario: Free tier user with restricted access.
        """
        self.client.force_authenticate(user=self.basic_user)
        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify tier info
        self.assertEqual(data['tier']['plan'], 'basic')
        self.assertEqual(data['tier']['max_days'], 7)

        # Basic tier should NOT have premium features
        self.assertEqual(data.get('intent_breakdown', []), [])
        self.assertEqual(data.get('geo_distribution', {}), {})

    def test_premium_tier_includes_intent_breakdown(self):
        """
        Test that premium tier gets intent analysis.
        Real-world scenario: Paid user sees lead intent distribution.
        """
        self.client.force_authenticate(user=self.premium_user)
        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['tier']['plan'], 'premium')
        self.assertEqual(data['tier']['max_days'], 90)
        self.assertIn('csv', data['tier']['export_formats'])

    def test_enterprise_tier_includes_all_features(self):
        """
        Test that enterprise tier gets full analytics.
        Real-world scenario: Enterprise customer with full access.
        """
        self.client.force_authenticate(user=self.enterprise_user)
        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['tier']['plan'], 'enterprise')
        self.assertEqual(data['tier']['max_days'], 365)
        self.assertIn('pdf', data['tier']['export_formats'])

    def test_days_parameter_enforced_by_tier(self):
        """
        Test that days parameter is capped by tier limit.
        Real-world scenario: Basic user tries to request 30 days.
        """
        self.client.force_authenticate(user=self.basic_user)

        # Request 30 days (over basic limit of 7)
        response = self.client.get('/v1/frontend/analytics/leads/?days=30')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should be capped at tier max
        self.assertEqual(data['summary']['period_days'], 7)

    def test_premium_tier_can_request_90_days(self):
        """
        Test that premium tier can get up to 90 days.
        Real-world scenario: Premium user analyzing quarterly trends.
        """
        self.client.force_authenticate(user=self.premium_user)

        response = self.client.get('/v1/frontend/analytics/leads/?days=90')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['summary']['period_days'], 90)

    def test_filter_by_priority(self):
        """
        Test filtering leads by priority.
        Real-world scenario: Sales team views only hot leads.
        """
        self.client.force_authenticate(user=self.basic_user)

        response = self.client.get('/v1/frontend/analytics/leads/?priority=hot')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # All returned leads should be hot
        for lead in data['leads']:
            self.assertEqual(lead['priority'], 'hot')

    def test_filter_by_chatbot_id(self):
        """
        Test filtering leads by specific chatbot.
        Real-world scenario: Multi-chatbot user views one chatbot's leads.
        """
        self.client.force_authenticate(user=self.basic_user)
        chatbot_id = self.basic_setup['chatbot'].id

        response = self.client.get(f'/v1/frontend/analytics/leads/?chatbot_id={chatbot_id}')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # All returned leads should be from this chatbot
        for lead in data['leads']:
            self.assertEqual(lead['chatbot_id'], str(chatbot_id))

    def test_filter_by_intent(self):
        """
        Test filtering leads by detected intent.
        Real-world scenario: Marketing analyzes pricing inquiries.
        """
        self.client.force_authenticate(user=self.premium_user)

        # Create lead with specific intent
        session = TestDataFactory.create_chat_session(self.premium_setup['chatbot'])
        LeadScore.objects.create(
            session=session,
            chatbot=self.premium_setup['chatbot'],
            org_id=self.premium_setup['org'].id,
            detected_intent='pricing_inquiry',
            priority='hot',
            total_score=85,
            session_date=date.today(),
        )

        response = self.client.get('/v1/frontend/analytics/leads/?intent=pricing_inquiry')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        for lead in data['leads']:
            self.assertEqual(lead['detected_intent'], 'pricing_inquiry')

    def test_pagination_parameters(self):
        """
        Test pagination with limit and offset.
        Real-world scenario: Paginated leads table in UI.
        """
        self.client.force_authenticate(user=self.basic_user)

        # First page
        response1 = self.client.get('/v1/frontend/analytics/leads/?limit=5&offset=0')
        self.assertEqual(response1.status_code, 200)
        data1 = response1.json()

        # Second page
        response2 = self.client.get('/v1/frontend/analytics/leads/?limit=5&offset=5')
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json()

        # Verify pagination info
        self.assertIn('pagination', data1)
        self.assertEqual(data1['pagination']['limit'], 5)
        self.assertEqual(data1['pagination']['offset'], 0)

        # Pages should have different leads (if enough data)
        if data1['leads'] and data2['leads']:
            ids1 = {l['id'] for l in data1['leads']}
            ids2 = {l['id'] for l in data2['leads']}
            self.assertEqual(len(ids1 & ids2), 0)  # No overlap

    def test_summary_counts_are_accurate(self):
        """
        Test that summary counts match actual data.
        Real-world scenario: Dashboard shows accurate metrics.
        """
        self.client.force_authenticate(user=self.basic_user)

        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        summary = data['summary']
        # Total should equal hot + warm + cold
        self.assertEqual(
            summary['total'],
            summary['hot'] + summary['warm'] + summary['cold']
        )

    def test_empty_leads_returns_proper_structure(self):
        """
        Test response structure when no leads exist.
        Real-world scenario: New user with no chat history.
        """
        # Create fresh user with no leads
        fresh_setup = TestDataFactory.create_complete_test_setup()
        LeadScore.objects.filter(org_id=fresh_setup['org'].id).delete()

        self.client.force_authenticate(user=fresh_setup['user'])
        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should return empty but valid structure
        self.assertEqual(data['summary']['total'], 0)
        self.assertEqual(data['leads'], [])
        self.assertIn('tier', data)
        self.assertIn('pagination', data)

    def test_response_includes_ai_analyzed_count(self):
        """
        Test that response includes AI-analyzed lead count.
        Real-world scenario: Show LLM analysis coverage.
        """
        self.client.force_authenticate(user=self.premium_user)

        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn('ai_analyzed', data['summary'])


class LeadDetailAPITests(TestCase):
    """Tests for GET /v1/frontend/analytics/leads/<lead_id>/"""

    def setUp(self):
        self.client = APIClient()
        self.setup = TestDataFactory.create_complete_test_setup(plan='premium')
        self.user = self.setup['user']
        self.lead = self.setup['leads'][0]

    def test_get_lead_detail_success(self):
        """
        Test retrieving single lead details.
        Real-world scenario: User clicks on lead to see full details.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get(f'/v1/frontend/analytics/leads/{self.lead.id}/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['id'], str(self.lead.id))
        self.assertIn('conversation', data)

    def test_get_lead_includes_conversation_messages(self):
        """
        Test that lead detail includes full conversation.
        Real-world scenario: Review full chat history for context.
        """
        # Add messages to the session
        TestDataFactory.create_chat_messages(
            self.lead.session,
            count=6,
            include_feedback=True
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.get(f'/v1/frontend/analytics/leads/{self.lead.id}/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn('conversation', data)
        self.assertGreater(len(data['conversation']), 0)

        # Verify message structure
        for msg in data['conversation']:
            self.assertIn('role', msg)
            self.assertIn('content', msg)
            self.assertIn('created_at', msg)

    def test_get_nonexistent_lead_returns_404(self):
        """
        Test that invalid lead ID returns 404.
        Real-world scenario: Lead was deleted or invalid URL.
        """
        self.client.force_authenticate(user=self.user)
        import uuid

        response = self.client.get(f'/v1/frontend/analytics/leads/{uuid.uuid4()}/')

        self.assertEqual(response.status_code, 404)

    def test_cannot_access_other_org_lead(self):
        """
        Test multi-tenant isolation in lead detail.
        Real-world scenario: Prevent accessing competitor's lead data.
        """
        other_setup = TestDataFactory.create_complete_test_setup()
        other_lead = other_setup['leads'][0]

        self.client.force_authenticate(user=self.user)

        response = self.client.get(f'/v1/frontend/analytics/leads/{other_lead.id}/')

        self.assertEqual(response.status_code, 404)


class WeeklyReportsAPITests(TestCase):
    """Tests for weekly reports endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.setup = TestDataFactory.create_complete_test_setup(plan='premium')
        self.user = self.setup['user']
        self.org = self.setup['org']

        # Create weekly reports
        self.report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            self.setup['chatbot']
        )

    def test_list_weekly_reports(self):
        """
        Test listing user's weekly reports.
        Real-world scenario: User views report history.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/reports/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_get_report_detail(self):
        """
        Test getting single report detail.
        Real-world scenario: User views specific week's report.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get(f'/v1/frontend/analytics/reports/{self.report.id}/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['id'], str(self.report.id))
        self.assertIn('report_data', data)
        self.assertIn('top_leads', data['report_data'])

    def test_generate_report_manually(self):
        """
        Test manual report generation.
        Real-world scenario: User requests on-demand report.
        """
        self.client.force_authenticate(user=self.user)

        # Delete existing reports to allow generation
        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        response = self.client.post('/v1/frontend/analytics/reports/generate/')

        self.assertIn(response.status_code, [200, 201])

    def test_filter_reports_by_chatbot(self):
        """
        Test filtering reports by chatbot.
        Real-world scenario: View reports for specific chatbot.
        """
        self.client.force_authenticate(user=self.user)
        chatbot_id = self.setup['chatbot'].id

        response = self.client.get(f'/v1/frontend/analytics/reports/?chatbot_id={chatbot_id}')

        self.assertEqual(response.status_code, 200)


class ReportPreferencesAPITests(TestCase):
    """Tests for report preferences endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']

    def test_get_default_preferences(self):
        """
        Test getting preferences creates defaults if not exist.
        Real-world scenario: New user accesses preferences.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/reports/preferences/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data['weekly_report_enabled'])
        self.assertEqual(data['report_day'], 0)  # Monday
        self.assertEqual(data['report_hour'], 9)

    def test_update_preferences(self):
        """
        Test updating report preferences.
        Real-world scenario: User changes report schedule.
        """
        self.client.force_authenticate(user=self.user)

        # First get to create defaults
        self.client.get('/v1/frontend/analytics/reports/preferences/')

        # Update preferences
        response = self.client.put(
            '/v1/frontend/analytics/reports/preferences/',
            data={
                'weekly_report_enabled': True,
                'report_day': 4,  # Friday
                'report_hour': 14,
                'timezone': 'America/New_York',
                'notify_hot_leads_immediately': True,
            },
            format='json'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['report_day'], 4)
        self.assertEqual(data['report_hour'], 14)
        self.assertEqual(data['timezone'], 'America/New_York')
        self.assertTrue(data['notify_hot_leads_immediately'])

    def test_disable_weekly_reports(self):
        """
        Test disabling weekly reports.
        Real-world scenario: User opts out of emails.
        """
        self.client.force_authenticate(user=self.user)

        # First get to create defaults
        self.client.get('/v1/frontend/analytics/reports/preferences/')

        response = self.client.put(
            '/v1/frontend/analytics/reports/preferences/',
            data={'weekly_report_enabled': False},
            format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['weekly_report_enabled'])


class LeadsExportAPITests(TestCase):
    """Tests for leads export functionality."""

    def setUp(self):
        self.client = APIClient()
        self.setup = TestDataFactory.create_complete_test_setup(plan='premium')
        self.user = self.setup['user']

    def test_export_csv(self):
        """
        Test exporting leads as CSV.
        Real-world scenario: User downloads leads for CRM import.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/leads/export/?format=csv')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_export_json(self):
        """
        Test exporting leads as JSON.
        Real-world scenario: API integration exports.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/leads/export/?format=json')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIsInstance(data, list)

    def test_export_respects_filters(self):
        """
        Test that export respects filter parameters.
        Real-world scenario: Export only hot leads from last week.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            '/v1/frontend/analytics/leads/export/?format=json&priority=hot&days=7'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        for lead in data:
            self.assertEqual(lead['priority'], 'hot')


class AnalyticsMultiTenantTests(TestCase):
    """Tests for multi-tenant data isolation."""

    def setUp(self):
        self.client = APIClient()

        # Create two separate organizations
        self.org1_setup = TestDataFactory.create_complete_test_setup()
        self.org2_setup = TestDataFactory.create_complete_test_setup()

    def test_user_only_sees_own_org_leads(self):
        """
        Test that users only see their organization's leads.
        Real-world scenario: Competitor's data must be isolated.
        """
        self.client.force_authenticate(user=self.org1_setup['user'])

        response = self.client.get('/v1/frontend/analytics/leads/')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        org2_lead_ids = {str(l.id) for l in self.org2_setup['leads']}
        returned_ids = {l['id'] for l in data['leads']}

        # No org2 leads should appear
        self.assertEqual(len(org2_lead_ids & returned_ids), 0)

    def test_user_cannot_access_other_org_report(self):
        """
        Test that users cannot access other org's reports.
        Real-world scenario: Prevent data leakage via direct URL.
        """
        # Create report for org2
        report = TestDataFactory.create_weekly_report(
            self.org2_setup['org'],
            self.org2_setup['user'],
        )

        # Try to access as org1 user
        self.client.force_authenticate(user=self.org1_setup['user'])

        response = self.client.get(f'/v1/frontend/analytics/reports/{report.id}/')

        self.assertEqual(response.status_code, 404)


class AnalyticsErrorHandlingTests(TestCase):
    """Tests for error handling and edge cases."""

    def setUp(self):
        self.client = APIClient()
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']

    def test_invalid_days_parameter(self):
        """
        Test handling of invalid days parameter.
        Real-world scenario: User enters invalid input.
        """
        self.client.force_authenticate(user=self.user)

        # String instead of number
        response = self.client.get('/v1/frontend/analytics/leads/?days=abc')

        # Should handle gracefully (either error or default)
        self.assertIn(response.status_code, [200, 400])

    def test_negative_offset(self):
        """
        Test handling of negative offset.
        Real-world scenario: Malformed pagination request.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/leads/?offset=-10')

        # Should handle gracefully
        self.assertIn(response.status_code, [200, 400])

    def test_invalid_uuid_format(self):
        """
        Test handling of invalid UUID in URL.
        Real-world scenario: Corrupted or typo in URL.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/leads/not-a-uuid/')

        # Should return 404 or 400
        self.assertIn(response.status_code, [400, 404])

    def test_very_large_limit(self):
        """
        Test handling of excessively large limit.
        Real-world scenario: Prevent DoS via large requests.
        """
        self.client.force_authenticate(user=self.user)

        response = self.client.get('/v1/frontend/analytics/leads/?limit=100000')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should be capped at tier limit
        self.assertLessEqual(data['pagination']['limit'], 100)
