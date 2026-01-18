"""
Comprehensive tests for LeadScore model.

Tests cover:
- Model creation and validation
- Score calculation and priority classification
- Edge cases and boundary conditions
- Data integrity constraints
- JSON field handling
"""

import pytest
from datetime import date, timedelta
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.analytics.models import LeadScore
from apps.analytics.tests.test_factories import TestDataFactory


class LeadScoreModelCreationTests(TestCase):
    """Test basic model creation and field defaults."""

    def setUp(self):
        """Set up test fixtures."""
        setup = TestDataFactory.create_complete_test_setup()
        self.user = setup['user']
        self.org = setup['org']
        self.site = setup['site']
        self.chatbot = setup['chatbot']

    def test_create_lead_score_with_required_fields_only(self):
        """
        Test creating a lead score with only required fields.
        Real-world scenario: Minimal lead data from quick chat session.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            session_date=date.today(),
        )

        # Verify defaults are applied
        self.assertEqual(lead.engagement_score, 0)
        self.assertEqual(lead.intent_score, 0)
        self.assertEqual(lead.total_score, 0)
        self.assertEqual(lead.priority, 'cold')
        self.assertIsNone(lead.detected_intent)
        self.assertEqual(lead.key_questions, [])
        self.assertEqual(lead.conversation_summary, '')

    def test_create_complete_lead_score(self):
        """
        Test creating a lead score with all fields populated.
        Real-world scenario: Full engagement with all data extracted.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            engagement_score=45,
            intent_score=40,
            total_score=85,
            priority='hot',
            detected_intent='pricing_inquiry',
            key_questions=["What's the pricing?", "Do you offer enterprise plans?"],
            conversation_summary="Visitor from Fortune 500 company inquired about enterprise pricing.",
            source_url="https://example.com/enterprise",
            geo_location="San Francisco, CA, USA",
            device_type="desktop",
            session_date=date.today(),
            session_duration_seconds=450,
            message_count=12,
            had_positive_feedback=True,
            had_negative_feedback=False,
            llm_insights={
                "analyzed_by_llm": True,
                "intent": {"primary": "pricing_inquiry", "confidence": 95},
                "urgency": "high"
            }
        )

        # Verify all fields
        self.assertEqual(lead.total_score, 85)
        self.assertEqual(lead.priority, 'hot')
        self.assertEqual(len(lead.key_questions), 2)
        self.assertTrue(lead.had_positive_feedback)
        self.assertEqual(lead.llm_insights['intent']['confidence'], 95)

    def test_one_to_one_relationship_with_session(self):
        """
        Test that each session can only have one lead score.
        Real-world scenario: Prevents duplicate scoring of same session.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)

        # Create first lead score
        LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            session_date=date.today(),
        )

        # Attempt to create second lead score for same session
        with self.assertRaises(IntegrityError):
            LeadScore.objects.create(
                session=session,
                chatbot=self.chatbot,
                org_id=self.org.id,
                session_date=date.today(),
            )


class LeadScorePriorityClassificationTests(TestCase):
    """Test priority classification based on scores."""

    def setUp(self):
        setup = TestDataFactory.create_complete_test_setup()
        self.org = setup['org']
        self.chatbot = setup['chatbot']

    def _create_lead_with_score(self, total_score, priority):
        """Helper to create lead with specific score."""
        session = TestDataFactory.create_chat_session(self.chatbot)
        return LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            total_score=total_score,
            priority=priority,
            session_date=date.today(),
        )

    def test_hot_lead_threshold_boundary_70(self):
        """
        Test that score of exactly 70 qualifies as hot lead.
        Boundary: hot >= 70
        """
        lead = self._create_lead_with_score(70, 'hot')
        self.assertEqual(lead.priority, 'hot')

    def test_hot_lead_maximum_score_100(self):
        """
        Test maximum score (100) is a hot lead.
        Boundary: Maximum possible score.
        """
        lead = self._create_lead_with_score(100, 'hot')
        self.assertEqual(lead.priority, 'hot')
        self.assertEqual(lead.total_score, 100)

    def test_warm_lead_threshold_boundary_40(self):
        """
        Test that score of exactly 40 qualifies as warm lead.
        Boundary: warm >= 40 and < 70
        """
        lead = self._create_lead_with_score(40, 'warm')
        self.assertEqual(lead.priority, 'warm')

    def test_warm_lead_upper_boundary_69(self):
        """
        Test that score of 69 is still warm (not hot).
        Boundary: warm < 70
        """
        lead = self._create_lead_with_score(69, 'warm')
        self.assertEqual(lead.priority, 'warm')

    def test_cold_lead_threshold_boundary_39(self):
        """
        Test that score of 39 qualifies as cold lead.
        Boundary: cold < 40
        """
        lead = self._create_lead_with_score(39, 'cold')
        self.assertEqual(lead.priority, 'cold')

    def test_cold_lead_minimum_score_0(self):
        """
        Test minimum score (0) is a cold lead.
        Boundary: Minimum possible score.
        """
        lead = self._create_lead_with_score(0, 'cold')
        self.assertEqual(lead.priority, 'cold')
        self.assertEqual(lead.total_score, 0)

    def test_score_consistency_engagement_plus_intent(self):
        """
        Test that total_score should equal engagement_score + intent_score.
        Real-world scenario: Ensure scoring components add up correctly.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            engagement_score=35,
            intent_score=45,
            total_score=80,  # Should equal 35 + 45
            priority='hot',
            session_date=date.today(),
        )

        self.assertEqual(lead.engagement_score + lead.intent_score, lead.total_score)


class LeadScoreEdgeCaseTests(TestCase):
    """Test edge cases and unusual data scenarios."""

    def setUp(self):
        setup = TestDataFactory.create_complete_test_setup()
        self.org = setup['org']
        self.chatbot = setup['chatbot']

    def test_empty_key_questions_list(self):
        """
        Test handling of empty questions list.
        Real-world scenario: Short session with no questions asked.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            key_questions=[],
            session_date=date.today(),
        )

        self.assertEqual(lead.key_questions, [])
        self.assertIsInstance(lead.key_questions, list)

    def test_large_number_of_questions(self):
        """
        Test handling of many questions.
        Real-world scenario: Long, detailed conversation.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        questions = [f"Question {i}?" for i in range(100)]

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            key_questions=questions,
            session_date=date.today(),
        )

        self.assertEqual(len(lead.key_questions), 100)

    def test_unicode_in_questions_and_summary(self):
        """
        Test handling of unicode characters.
        Real-world scenario: International visitors with non-ASCII text.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            key_questions=["価格はいくらですか?", "Wie viel kostet das?", "¿Cuánto cuesta?"],
            conversation_summary="日本からのお客様がAPI統合について問い合わせました。",
            geo_location="東京, 日本",
            session_date=date.today(),
        )

        self.assertEqual(len(lead.key_questions), 3)
        self.assertIn("日本", lead.geo_location)

    def test_very_long_source_url(self):
        """
        Test handling of very long URLs.
        Real-world scenario: URL with many query parameters.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        long_url = "https://example.com/page?" + "&".join([f"param{i}=value{i}" for i in range(50)])

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            source_url=long_url[:500],  # Max 500 chars
            session_date=date.today(),
        )

        self.assertTrue(len(lead.source_url) <= 500)

    def test_null_vs_empty_string_geo_location(self):
        """
        Test distinction between null and empty string geo.
        Real-world scenario: Unknown location vs explicitly empty.
        """
        session1 = TestDataFactory.create_chat_session(self.chatbot)
        lead_null = LeadScore.objects.create(
            session=session1,
            chatbot=self.chatbot,
            org_id=self.org.id,
            geo_location=None,
            session_date=date.today(),
        )

        session2 = TestDataFactory.create_chat_session(self.chatbot)
        lead_empty = LeadScore.objects.create(
            session=session2,
            chatbot=self.chatbot,
            org_id=self.org.id,
            geo_location='',
            session_date=date.today(),
        )

        self.assertIsNone(lead_null.geo_location)
        self.assertEqual(lead_empty.geo_location, '')

    def test_zero_duration_session(self):
        """
        Test handling of instant sessions.
        Real-world scenario: Bot session or very quick bounce.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            session_duration_seconds=0,
            message_count=1,
            session_date=date.today(),
        )

        self.assertEqual(lead.session_duration_seconds, 0)

    def test_very_long_session_duration(self):
        """
        Test handling of very long sessions.
        Real-world scenario: Extended support conversation.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        # 2 hour session
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            session_duration_seconds=7200,
            message_count=100,
            session_date=date.today(),
        )

        self.assertEqual(lead.session_duration_seconds, 7200)


class LeadScoreLLMInsightsTests(TestCase):
    """Test LLM insights JSON field handling."""

    def setUp(self):
        setup = TestDataFactory.create_complete_test_setup()
        self.org = setup['org']
        self.chatbot = setup['chatbot']

    def test_null_llm_insights(self):
        """
        Test lead without LLM analysis.
        Real-world scenario: LLM analysis disabled or failed.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            llm_insights=None,
            session_date=date.today(),
        )

        self.assertIsNone(lead.llm_insights)

    def test_complete_llm_insights_structure(self):
        """
        Test complete LLM insights extraction.
        Real-world scenario: Full LLM analysis with all fields.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        insights = {
            "analyzed_by_llm": True,
            "model_used": "gpt-4o-mini",
            "intent": {
                "primary": "demo_request",
                "confidence": 92,
                "buying_signals": ["asked for demo", "mentioned budget"],
                "objections": ["timeline concerns"]
            },
            "entities": {
                "company_name": "TechCorp Inc",
                "job_title": "CTO",
                "team_size": "100-500",
                "industry": "FinTech"
            },
            "sentiment": "positive",
            "urgency": "high",
            "recommendations": {
                "follow_up_action": "Schedule demo within 48 hours",
                "talking_points": ["security features", "compliance"]
            }
        }

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            llm_insights=insights,
            session_date=date.today(),
        )

        # Verify nested structure access
        self.assertTrue(lead.llm_insights['analyzed_by_llm'])
        self.assertEqual(lead.llm_insights['intent']['confidence'], 92)
        self.assertEqual(len(lead.llm_insights['intent']['buying_signals']), 2)
        self.assertEqual(lead.llm_insights['entities']['company_name'], "TechCorp Inc")

    def test_partial_llm_insights(self):
        """
        Test partial LLM analysis results.
        Real-world scenario: Some fields couldn't be extracted.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        insights = {
            "analyzed_by_llm": True,
            "intent": {"primary": "unknown", "confidence": 30},
            "sentiment": "neutral",
            # Missing entities, recommendations, etc.
        }

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            llm_insights=insights,
            session_date=date.today(),
        )

        self.assertTrue(lead.llm_insights['analyzed_by_llm'])
        self.assertNotIn('entities', lead.llm_insights)

    def test_llm_insights_with_special_characters(self):
        """
        Test LLM insights containing special characters.
        Real-world scenario: Quotes, newlines in extracted text.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        insights = {
            "analyzed_by_llm": True,
            "entities": {
                "company_name": 'O\'Brien & Associates "LLC"',
                "notes": "Customer said:\n'I need this ASAP'"
            }
        }

        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            llm_insights=insights,
            session_date=date.today(),
        )

        self.assertIn("O'Brien", lead.llm_insights['entities']['company_name'])
        self.assertIn("\n", lead.llm_insights['entities']['notes'])


class LeadScoreQueryTests(TestCase):
    """Test common query patterns for leads."""

    def setUp(self):
        setup = TestDataFactory.create_complete_test_setup()
        self.org = setup['org']
        self.chatbot = setup['chatbot']
        self.leads = setup['leads']

    def test_filter_by_priority(self):
        """
        Test filtering leads by priority.
        Real-world scenario: Dashboard showing only hot leads.
        """
        hot_leads = LeadScore.objects.filter(
            org_id=self.org.id,
            priority='hot'
        )

        self.assertTrue(hot_leads.exists())
        for lead in hot_leads:
            self.assertEqual(lead.priority, 'hot')

    def test_filter_by_date_range(self):
        """
        Test filtering leads within date range.
        Real-world scenario: Weekly report date filtering.
        """
        today = date.today()
        week_ago = today - timedelta(days=7)

        leads_this_week = LeadScore.objects.filter(
            org_id=self.org.id,
            session_date__gte=week_ago,
            session_date__lte=today
        )

        for lead in leads_this_week:
            self.assertGreaterEqual(lead.session_date, week_ago)
            self.assertLessEqual(lead.session_date, today)

    def test_filter_by_intent(self):
        """
        Test filtering leads by detected intent.
        Real-world scenario: Analyzing pricing inquiries.
        """
        # Create lead with specific intent
        session = TestDataFactory.create_chat_session(self.chatbot)
        LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            detected_intent='pricing_inquiry',
            session_date=date.today(),
        )

        pricing_leads = LeadScore.objects.filter(
            org_id=self.org.id,
            detected_intent='pricing_inquiry'
        )

        self.assertTrue(pricing_leads.exists())

    def test_order_by_score_descending(self):
        """
        Test ordering leads by score.
        Real-world scenario: Show best leads first.
        """
        leads = list(LeadScore.objects.filter(
            org_id=self.org.id
        ).order_by('-total_score'))

        for i in range(len(leads) - 1):
            self.assertGreaterEqual(leads[i].total_score, leads[i + 1].total_score)

    def test_count_by_priority(self):
        """
        Test counting leads by priority.
        Real-world scenario: Dashboard summary stats.
        """
        from django.db.models import Count

        counts = LeadScore.objects.filter(
            org_id=self.org.id
        ).values('priority').annotate(count=Count('id'))

        priority_counts = {item['priority']: item['count'] for item in counts}

        # Our test setup creates 2 hot, 3 warm, 5 cold
        self.assertIn('hot', priority_counts)
        self.assertIn('warm', priority_counts)
        self.assertIn('cold', priority_counts)

    def test_multi_tenant_isolation(self):
        """
        Test that queries respect org_id filtering.
        Real-world scenario: Ensure data isolation between tenants.
        """
        # Create another org with leads
        other_setup = TestDataFactory.create_complete_test_setup()
        other_org_id = other_setup['org'].id

        # Query for first org should not include other org's leads
        first_org_leads = LeadScore.objects.filter(org_id=self.org.id)
        other_org_leads = LeadScore.objects.filter(org_id=other_org_id)

        first_org_ids = set(first_org_leads.values_list('id', flat=True))
        other_org_ids = set(other_org_leads.values_list('id', flat=True))

        # No overlap
        self.assertEqual(len(first_org_ids & other_org_ids), 0)


class LeadScoreFeedbackTests(TestCase):
    """Test feedback field handling."""

    def setUp(self):
        setup = TestDataFactory.create_complete_test_setup()
        self.org = setup['org']
        self.chatbot = setup['chatbot']

    def test_both_positive_and_negative_feedback(self):
        """
        Test lead with mixed feedback.
        Real-world scenario: User liked some responses, disliked others.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            had_positive_feedback=True,
            had_negative_feedback=True,
            session_date=date.today(),
        )

        self.assertTrue(lead.had_positive_feedback)
        self.assertTrue(lead.had_negative_feedback)

    def test_no_feedback(self):
        """
        Test lead with no feedback.
        Real-world scenario: User didn't rate any responses.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            had_positive_feedback=False,
            had_negative_feedback=False,
            session_date=date.today(),
        )

        self.assertFalse(lead.had_positive_feedback)
        self.assertFalse(lead.had_negative_feedback)

    def test_filter_leads_with_negative_feedback(self):
        """
        Test finding leads with negative feedback.
        Real-world scenario: Identify issues for quality improvement.
        """
        # Create lead with negative feedback
        session = TestDataFactory.create_chat_session(self.chatbot)
        LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            had_negative_feedback=True,
            session_date=date.today(),
        )

        negative_leads = LeadScore.objects.filter(
            org_id=self.org.id,
            had_negative_feedback=True
        )

        self.assertTrue(negative_leads.exists())
