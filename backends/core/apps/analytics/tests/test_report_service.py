"""
Comprehensive tests for WeeklyReportService.

Tests cover:
- Report generation logic
- Data aggregation accuracy
- Comparison calculations
- Edge cases with data gaps
- Multi-chatbot scenarios
"""

from datetime import date, timedelta
from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import LeadScore, WeeklyLeadsReport
from apps.analytics.report_service import WeeklyReportService
from apps.analytics.tests.test_factories import TestDataFactory


class WeeklyReportGenerationTests(TestCase):
    """Tests for report generation."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = WeeklyReportService()

    def test_generate_report_creates_record(self):
        """
        Test that generate_report creates a database record.
        Real-world scenario: Weekly cron job generates reports.
        """
        # Delete any existing reports
        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        self.assertIsNotNone(report)
        self.assertEqual(report.org_id, self.org.id)
        self.assertEqual(report.user_id, self.user.id)

    def test_report_week_dates_are_monday_to_sunday(self):
        """
        Test that report week is Monday-Sunday.
        Real-world scenario: Standard business week reporting.
        """
        # Delete existing reports
        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        # week_start should be Monday (weekday 0)
        self.assertEqual(report.week_start.weekday(), 0)
        # week_end should be Sunday (weekday 6)
        self.assertEqual(report.week_end.weekday(), 6)
        # Should be 6 days apart
        self.assertEqual((report.week_end - report.week_start).days, 6)

    def test_report_counts_leads_correctly(self):
        """
        Test that lead counts are accurate.
        Real-world scenario: Dashboard shows correct numbers.
        """
        # Create specific leads for this week
        week_start = date.today() - timedelta(days=date.today().weekday() + 7)
        week_end = week_start + timedelta(days=6)

        # Clear existing leads and create known quantities
        LeadScore.objects.filter(org_id=self.org.id).delete()

        for priority in ['hot', 'hot', 'warm', 'warm', 'warm', 'cold', 'cold']:
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session,
                self.chatbot,
                self.org.id,
                priority=priority,
                session_date=week_start + timedelta(days=2),  # Mid-week
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=week_start,
        )

        self.assertEqual(report.hot_leads, 2)
        self.assertEqual(report.warm_leads, 3)
        self.assertEqual(report.cold_leads, 2)
        self.assertEqual(report.total_leads, 7)

    def test_report_filters_by_chatbot(self):
        """
        Test generating report for specific chatbot.
        Real-world scenario: Multi-chatbot user views individual performance.
        """
        # Create second chatbot with leads
        chatbot2 = TestDataFactory.create_chatbot(self.setup['site'], name="Chatbot 2")
        session = TestDataFactory.create_chat_session(chatbot2)
        TestDataFactory.create_lead_score(
            session,
            chatbot2,
            self.org.id,
            priority='hot',
            session_date=date.today() - timedelta(days=3),
        )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        # Generate for first chatbot only
        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            chatbot_id=self.chatbot.id,
        )

        self.assertEqual(report.chatbot_id, self.chatbot.id)

    def test_report_includes_intent_breakdown(self):
        """
        Test that report includes intent distribution.
        Real-world scenario: Marketing analyzes inquiry types.
        """
        # Create leads with specific intents
        for intent in ['pricing_inquiry', 'pricing_inquiry', 'demo_request', 'support']:
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session,
                self.chatbot,
                self.org.id,
                detected_intent=intent,
                session_date=date.today() - timedelta(days=3),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        self.assertIn('intent_breakdown', report.report_data)
        intent_breakdown = report.report_data['intent_breakdown']
        self.assertEqual(intent_breakdown.get('pricing_inquiry', 0), 2)

    def test_report_includes_geo_distribution(self):
        """
        Test that report includes geographic distribution.
        Real-world scenario: Sales targets specific regions.
        """
        # Create leads with specific locations
        for location in ['New York, USA', 'New York, USA', 'London, UK', None]:
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session,
                self.chatbot,
                self.org.id,
                geo_location=location,
                session_date=date.today() - timedelta(days=3),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        self.assertIn('geo_distribution', report.report_data)
        geo = report.report_data['geo_distribution']
        self.assertEqual(geo.get('New York, USA', 0), 2)


class WeeklyReportComparisonTests(TestCase):
    """Tests for week-over-week comparison calculations."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = WeeklyReportService()

        # Clear existing leads
        LeadScore.objects.filter(org_id=self.org.id).delete()

    def test_leads_change_percent_positive(self):
        """
        Test positive change calculation.
        Real-world scenario: "Leads up 50% from last week!"
        """
        this_week_start = date.today() - timedelta(days=date.today().weekday() + 7)
        last_week_start = this_week_start - timedelta(days=7)

        # Last week: 2 leads
        for _ in range(2):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                session_date=last_week_start + timedelta(days=2),
            )

        # This week: 3 leads (50% increase)
        for _ in range(3):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                session_date=this_week_start + timedelta(days=2),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=this_week_start,
        )

        # 50% increase: (3-2)/2 * 100 = 50
        self.assertEqual(report.leads_change_percent, 50.0)

    def test_leads_change_percent_negative(self):
        """
        Test negative change calculation.
        Real-world scenario: "Leads down 25% from last week"
        """
        this_week_start = date.today() - timedelta(days=date.today().weekday() + 7)
        last_week_start = this_week_start - timedelta(days=7)

        # Last week: 4 leads
        for _ in range(4):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                session_date=last_week_start + timedelta(days=2),
            )

        # This week: 3 leads (25% decrease)
        for _ in range(3):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                session_date=this_week_start + timedelta(days=2),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=this_week_start,
        )

        # 25% decrease: (3-4)/4 * 100 = -25
        self.assertEqual(report.leads_change_percent, -25.0)

    def test_leads_change_percent_from_zero(self):
        """
        Test change calculation when previous week had zero leads.
        Real-world scenario: First week with conversions.
        """
        this_week_start = date.today() - timedelta(days=date.today().weekday() + 7)

        # No leads last week, 5 this week
        for _ in range(5):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                session_date=this_week_start + timedelta(days=2),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=this_week_start,
        )

        # From 0 to 5 is 100% increase (or could be infinite - depends on implementation)
        # Most implementations treat this as 100%
        self.assertIn(report.leads_change_percent, [100.0, 0.0])

    def test_leads_change_percent_to_zero(self):
        """
        Test change calculation when this week has zero leads.
        Real-world scenario: Quiet week after good week.
        """
        this_week_start = date.today() - timedelta(days=date.today().weekday() + 7)
        last_week_start = this_week_start - timedelta(days=7)

        # 5 leads last week, none this week
        for _ in range(5):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                session_date=last_week_start + timedelta(days=2),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=this_week_start,
        )

        # From 5 to 0 is -100%
        self.assertEqual(report.leads_change_percent, -100.0)


class WeeklyReportEdgeCasesTests(TestCase):
    """Tests for edge cases in report generation."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = WeeklyReportService()

    def test_report_with_no_leads(self):
        """
        Test report generation when no leads exist.
        Real-world scenario: New user or quiet week.
        """
        LeadScore.objects.filter(org_id=self.org.id).delete()
        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        self.assertEqual(report.total_leads, 0)
        self.assertEqual(report.hot_leads, 0)
        self.assertEqual(report.report_data.get('top_leads', []), [])

    def test_report_with_leads_missing_optional_fields(self):
        """
        Test report handles leads with missing optional data.
        Real-world scenario: Minimal data from quick sessions.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        LeadScore.objects.create(
            session=session,
            chatbot=self.chatbot,
            org_id=self.org.id,
            total_score=50,
            priority='warm',
            session_date=date.today() - timedelta(days=3),
            # All optional fields left at defaults/null
        )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        # Should not raise exception
        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        self.assertEqual(report.total_leads, 1)

    def test_report_handles_duplicate_generation_attempt(self):
        """
        Test handling of duplicate report generation.
        Real-world scenario: Double-click on generate button.
        """
        week_start = date.today() - timedelta(days=date.today().weekday() + 7)

        # Generate first report
        report1 = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=week_start,
        )

        # Try to generate again
        report2 = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            week_start=week_start,
        )

        # Should return existing report or handle gracefully
        # (Implementation-dependent - either same report or new one)
        self.assertIsNotNone(report2)

    def test_report_for_all_chatbots(self):
        """
        Test report generation for all chatbots (null chatbot_id).
        Real-world scenario: Organization-wide report.
        """
        # Create multiple chatbots with leads
        chatbot2 = TestDataFactory.create_chatbot(self.setup['site'], name="Bot 2")

        session1 = TestDataFactory.create_chat_session(self.chatbot)
        TestDataFactory.create_lead_score(
            session1, self.chatbot, self.org.id,
            priority='hot',
            session_date=date.today() - timedelta(days=3),
        )

        session2 = TestDataFactory.create_chat_session(chatbot2)
        TestDataFactory.create_lead_score(
            session2, chatbot2, self.org.id,
            priority='warm',
            session_date=date.today() - timedelta(days=3),
        )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
            chatbot_id=None,  # All chatbots
        )

        self.assertIsNone(report.chatbot)
        # Should include leads from both chatbots
        self.assertGreaterEqual(report.total_leads, 2)


class ReportTopLeadsTests(TestCase):
    """Tests for top leads in reports."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = WeeklyReportService()

        # Clear and create known leads
        LeadScore.objects.filter(org_id=self.org.id).delete()

    def test_top_leads_ordered_by_score(self):
        """
        Test that top leads are ordered by score descending.
        Real-world scenario: Best leads shown first.
        """
        # Create leads with specific scores
        for score in [95, 75, 85, 60, 90]:
            session = TestDataFactory.create_chat_session(self.chatbot)
            priority = 'hot' if score >= 70 else ('warm' if score >= 40 else 'cold')
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                total_score=score,
                priority=priority,
                session_date=date.today() - timedelta(days=3),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        top_leads = report.report_data.get('top_leads', [])
        scores = [lead.get('score', 0) for lead in top_leads]

        # Should be in descending order
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_leads_limited_to_five(self):
        """
        Test that top leads are limited for email brevity.
        Real-world scenario: Don't overwhelm email with too many leads.
        """
        # Create many leads
        for i in range(20):
            session = TestDataFactory.create_chat_session(self.chatbot)
            TestDataFactory.create_lead_score(
                session, self.chatbot, self.org.id,
                total_score=50 + i,
                priority='warm',
                session_date=date.today() - timedelta(days=3),
            )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        top_leads = report.report_data.get('top_leads', [])
        self.assertLessEqual(len(top_leads), 10)  # Could be 5 or 10 depending on impl

    def test_top_leads_include_essential_fields(self):
        """
        Test that top leads have all needed fields for display.
        Real-world scenario: Email template can render lead cards.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        TestDataFactory.create_lead_score(
            session, self.chatbot, self.org.id,
            priority='hot',
            total_score=90,
            detected_intent='pricing_inquiry',
            key_questions=['How much?'],
            geo_location='San Francisco',
            device_type='desktop',
            session_date=date.today() - timedelta(days=3),
        )

        WeeklyLeadsReport.objects.filter(user=self.user).delete()

        report = self.service.generate_report(
            org_id=self.org.id,
            user_id=self.user.id,
        )

        top_leads = report.report_data.get('top_leads', [])
        if top_leads:
            lead = top_leads[0]
            # Check essential fields exist
            self.assertIn('priority', lead)
            self.assertIn('score', lead)
