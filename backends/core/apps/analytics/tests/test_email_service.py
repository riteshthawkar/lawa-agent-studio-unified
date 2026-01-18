"""
Comprehensive tests for email service.

Tests cover:
- Email rendering with various data scenarios
- Email delivery simulation
- Error handling and retry logic
- Template context building
- Edge cases with missing/malformed data
"""

from datetime import date, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core import mail
from django.template.loader import render_to_string

from apps.analytics.email_service import ReportEmailService
from apps.analytics.models import WeeklyLeadsReport, LeadScore
from apps.analytics.tests.test_factories import TestDataFactory


class WeeklyReportEmailTests(TestCase):
    """Tests for weekly report email sending."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup(plan='premium')
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = ReportEmailService()

    def test_send_weekly_report_success(self):
        """
        Test successful email sending.
        Real-world scenario: Monday morning report delivery.
        """
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            self.chatbot,
            total_leads=25,
        )

        result = self.service.send_weekly_report(self.user, report)

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)

        # Verify email was marked as sent
        report.refresh_from_db()
        self.assertTrue(report.email_sent)
        self.assertIsNotNone(report.email_sent_at)
        self.assertEqual(report.email_error, '')

    def test_email_subject_with_hot_leads(self):
        """
        Test email subject when hot leads exist.
        Real-world scenario: Attention-grabbing subject for important leads.
        """
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            hot_leads=5,
            total_leads=20,
        )
        report.refresh_from_db()  # Ensure data is saved

        self.service.send_weekly_report(self.user, report)

        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn('Hot Lead', subject)
        self.assertIn('5', subject)

    def test_email_subject_with_no_hot_leads(self):
        """
        Test email subject when no hot leads.
        Real-world scenario: Normal week with warm/cold leads only.
        """
        report = WeeklyLeadsReport.objects.create(
            org=self.org,
            user=self.user,
            chatbot=self.chatbot,
            week_start=date.today() - timedelta(days=7),
            week_end=date.today() - timedelta(days=1),
            total_sessions=50,
            total_leads=15,
            hot_leads=0,
            warm_leads=8,
            cold_leads=7,
            report_data={},
        )

        self.service.send_weekly_report(self.user, report)

        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn('15', subject)
        self.assertIn(self.chatbot.name, subject)

    def test_email_subject_with_zero_leads(self):
        """
        Test email subject when no leads this week.
        Real-world scenario: Quiet week with no conversions.
        """
        report = WeeklyLeadsReport.objects.create(
            org=self.org,
            user=self.user,
            chatbot=self.chatbot,
            week_start=date.today() - timedelta(days=7),
            week_end=date.today() - timedelta(days=1),
            total_sessions=10,
            total_leads=0,
            hot_leads=0,
            warm_leads=0,
            cold_leads=0,
            report_data={},
        )

        self.service.send_weekly_report(self.user, report)

        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        # Should show date range
        self.assertIn('Weekly Leads Report', subject)

    def test_email_contains_html_and_text(self):
        """
        Test that email has both HTML and plain text versions.
        Real-world scenario: Support for all email clients.
        """
        report = TestDataFactory.create_weekly_report(self.org, self.user)

        self.service.send_weekly_report(self.user, report)

        email = mail.outbox[0]
        self.assertIsNotNone(email.body)  # Plain text
        self.assertEqual(len(email.alternatives), 1)  # HTML
        self.assertEqual(email.alternatives[0][1], 'text/html')

    def test_email_handles_failed_delivery(self):
        """
        Test error handling when email fails.
        Real-world scenario: SMTP server down or rate limited.
        """
        report = TestDataFactory.create_weekly_report(self.org, self.user)

        with patch('django.core.mail.EmailMultiAlternatives.send') as mock_send:
            mock_send.side_effect = Exception("SMTP connection failed")

            result = self.service.send_weekly_report(self.user, report)

            self.assertFalse(result)

            # Verify error was recorded
            report.refresh_from_db()
            self.assertFalse(report.email_sent)
            self.assertIn('SMTP', report.email_error)


class EmailContextBuildingTests(TestCase):
    """Tests for building email template context."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = ReportEmailService()

    def test_context_includes_user_name(self):
        """
        Test that context has user's name for personalization.
        Real-world scenario: "Hi John, here's your report..."
        """
        report = TestDataFactory.create_weekly_report(self.org, self.user)

        context = self.service._build_email_context(self.user, report)

        self.assertIn('user_name', context)
        self.assertIsNotNone(context['user_name'])

    def test_context_with_user_without_name(self):
        """
        Test context building when user has no name set.
        Real-world scenario: User registered with email only.
        """
        self.user.name = None
        self.user.save()

        report = TestDataFactory.create_weekly_report(self.org, self.user)
        context = self.service._build_email_context(self.user, report)

        # Should fallback to email prefix
        self.assertIsNotNone(context['user_name'])
        self.assertIn('@', self.user.email.split('@')[0])

    def test_context_includes_trend_indicators(self):
        """
        Test that context includes trend direction.
        Real-world scenario: "Leads up 25% from last week!"
        """
        report = WeeklyLeadsReport.objects.create(
            org=self.org,
            user=self.user,
            week_start=date.today() - timedelta(days=7),
            week_end=date.today() - timedelta(days=1),
            total_leads=50,
            leads_change_percent=25.5,
            sessions_change_percent=-10.0,
            report_data={},
        )

        context = self.service._build_email_context(self.user, report)

        self.assertEqual(context['leads_trend'], 'up')
        self.assertEqual(context['sessions_trend'], 'down')
        self.assertEqual(context['leads_change_percent'], 25.5)

    def test_context_includes_top_leads_with_llm_insights(self):
        """
        Test that top leads include LLM-extracted data.
        Real-world scenario: Show buying signals in email.
        """
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            report_data={
                'top_leads': [
                    {
                        'id': 'test-id',
                        'priority': 'hot',
                        'score': 90,
                        'llm_insights': {
                            'analyzed_by_llm': True,
                            'intent': {
                                'primary': 'pricing',
                                'buying_signals': ['asked about pricing', 'mentioned budget']
                            },
                            'entities': {
                                'company_name': 'Acme Corp'
                            }
                        }
                    }
                ],
                'intent_breakdown': {'pricing': 10},
            }
        )

        context = self.service._build_email_context(self.user, report)

        self.assertIn('top_leads', context)
        self.assertGreater(len(context['top_leads']), 0)

        lead = context['top_leads'][0]
        self.assertIn('buying_signals', lead)
        self.assertIn('company_name', lead)

    def test_context_handles_empty_report_data(self):
        """
        Test context building with empty report data.
        Real-world scenario: Report generated but no activity.
        """
        report = WeeklyLeadsReport.objects.create(
            org=self.org,
            user=self.user,
            week_start=date.today() - timedelta(days=7),
            week_end=date.today() - timedelta(days=1),
            total_leads=0,
            report_data={},
        )

        context = self.service._build_email_context(self.user, report)

        self.assertEqual(context['top_leads'], [])
        self.assertEqual(context['intent_breakdown'], [])
        self.assertEqual(context['geo_distribution'], [])

    def test_context_includes_dashboard_url(self):
        """
        Test that context has correct dashboard URL.
        Real-world scenario: CTA button links to dashboard.
        """
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            self.chatbot
        )

        context = self.service._build_email_context(self.user, report)

        self.assertIn('dashboard_url', context)
        self.assertIn('/analytics/leads', context['dashboard_url'])
        self.assertIn(str(self.chatbot.id), context['dashboard_url'])


class HotLeadNotificationTests(TestCase):
    """Tests for immediate hot lead notifications."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.chatbot = self.setup['chatbot']
        self.service = ReportEmailService()

    def test_send_hot_lead_notification_success(self):
        """
        Test sending immediate hot lead alert.
        Real-world scenario: Sales team gets notified of hot prospect.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = TestDataFactory.create_lead_score(
            session,
            self.chatbot,
            self.org.id,
            priority='hot',
            total_score=92,
            detected_intent='demo_request',
        )

        result = self.service.send_hot_lead_notification(self.user, lead)

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertIn('Hot Lead', email.subject)
        self.assertIn('demo_request', email.subject.lower().replace('-', '_').replace(' ', '_')
                      if 'demo' in email.subject.lower() else email.subject)

    def test_hot_lead_email_includes_key_info(self):
        """
        Test that hot lead email contains essential details.
        Real-world scenario: Sales can act without opening dashboard.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = TestDataFactory.create_lead_score(
            session,
            self.chatbot,
            self.org.id,
            priority='hot',
            total_score=88,
            key_questions=["What's the pricing?", "Do you have an API?"],
            conversation_summary="Enterprise prospect from Fortune 500",
            geo_location="New York, NY, USA",
        )

        self.service.send_hot_lead_notification(self.user, lead)

        email = mail.outbox[0]
        html_content = email.alternatives[0][0]

        # Check key information is present
        self.assertIn('88', html_content)  # Score
        self.assertIn('pricing', html_content.lower())  # Question
        self.assertIn('New York', html_content)  # Location

    def test_hot_lead_notification_failure_handling(self):
        """
        Test graceful handling of notification failure.
        Real-world scenario: Email service temporary outage.
        """
        session = TestDataFactory.create_chat_session(self.chatbot)
        lead = TestDataFactory.create_lead_score(
            session, self.chatbot, self.org.id, priority='hot'
        )

        with patch('django.core.mail.EmailMultiAlternatives.send') as mock_send:
            mock_send.side_effect = Exception("Rate limited")

            result = self.service.send_hot_lead_notification(self.user, lead)

            self.assertFalse(result)


class ScheduledReportDeliveryTests(TestCase):
    """Tests for scheduled report delivery."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']
        self.service = ReportEmailService()

        # Create report preferences
        TestDataFactory.create_report_preferences(
            self.user,
            self.org,
            report_day=0,  # Monday
            report_hour=9,
        )

    def test_send_reports_for_day_finds_matching_users(self):
        """
        Test that scheduled delivery finds correct users.
        Real-world scenario: Monday 9AM report batch job.
        """
        # Create unsent report
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            email_sent=False,
        )

        count = self.service.send_reports_for_day(day_of_week=0, hour=9)

        self.assertGreaterEqual(count, 1)

    def test_send_reports_skips_wrong_schedule(self):
        """
        Test that wrong day/hour doesn't send.
        Real-world scenario: Don't send Friday's reports on Monday.
        """
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            email_sent=False,
        )

        # Wrong day (Friday) and wrong hour
        count = self.service.send_reports_for_day(day_of_week=4, hour=15)

        self.assertEqual(count, 0)

    def test_send_reports_skips_already_sent(self):
        """
        Test that already-sent reports aren't re-sent.
        Real-world scenario: Prevent duplicate emails on retry.
        """
        report = TestDataFactory.create_weekly_report(
            self.org,
            self.user,
            email_sent=True,
        )

        count = self.service.send_reports_for_day(day_of_week=0, hour=9)

        self.assertEqual(count, 0)


class EmailTemplateRenderingTests(TestCase):
    """Tests for email template rendering edge cases."""

    def setUp(self):
        self.setup = TestDataFactory.create_complete_test_setup()
        self.user = self.setup['user']
        self.org = self.setup['org']

    def test_template_renders_with_minimal_data(self):
        """
        Test template works with minimal context.
        Real-world scenario: New user with no historical data.
        """
        context = {
            'user_name': 'Test User',
            'week_start': date.today() - timedelta(days=7),
            'week_end': date.today() - timedelta(days=1),
            'total_leads': 0,
            'hot_leads': 0,
            'warm_leads': 0,
            'cold_leads': 0,
            'total_sessions': 0,
            'leads_trend': 'flat',
            'leads_change_percent': 0,
            'sessions_trend': 'flat',
            'sessions_change_percent': 0,
            'top_leads': [],
            'intent_breakdown': [],
            'geo_distribution': [],
            'daily_trend': [],
            'chatbot_name': 'Test Bot',
            'dashboard_url': 'https://example.com',
            'settings_url': 'https://example.com/settings',
            'unsubscribe_url': 'https://example.com/unsubscribe',
            'current_year': 2025,
        }

        # Should not raise exception
        html = render_to_string('emails/weekly_leads_report.html', context)

        self.assertIn('Test User', html)
        self.assertIn('Test Bot', html)

    def test_template_escapes_user_input(self):
        """
        Test that user input is properly escaped.
        Real-world scenario: Prevent XSS in emails.
        """
        context = {
            'user_name': '<script>alert("xss")</script>',
            'week_start': date.today() - timedelta(days=7),
            'week_end': date.today() - timedelta(days=1),
            'total_leads': 0,
            'hot_leads': 0,
            'warm_leads': 0,
            'cold_leads': 0,
            'total_sessions': 0,
            'leads_trend': 'flat',
            'leads_change_percent': 0,
            'sessions_trend': 'flat',
            'sessions_change_percent': 0,
            'top_leads': [],
            'intent_breakdown': [],
            'geo_distribution': [],
            'daily_trend': [],
            'chatbot_name': 'Test',
            'dashboard_url': 'https://example.com',
            'settings_url': 'https://example.com/settings',
            'unsubscribe_url': 'https://example.com/unsubscribe',
            'current_year': 2025,
        }

        html = render_to_string('emails/weekly_leads_report.html', context)

        # Script tag should be escaped
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_template_handles_unicode(self):
        """
        Test template handles international characters.
        Real-world scenario: International user names and locations.
        """
        context = {
            'user_name': '田中太郎',
            'week_start': date.today() - timedelta(days=7),
            'week_end': date.today() - timedelta(days=1),
            'total_leads': 5,
            'hot_leads': 1,
            'warm_leads': 2,
            'cold_leads': 2,
            'total_sessions': 10,
            'leads_trend': 'up',
            'leads_change_percent': 25,
            'sessions_trend': 'up',
            'sessions_change_percent': 10,
            'top_leads': [
                {
                    'priority': 'hot',
                    'score': 85,
                    'intent': 'pricing',
                    'geo': '東京, 日本',
                    'buying_signals': [],
                }
            ],
            'intent_breakdown': [],
            'geo_distribution': [('東京', 5)],
            'daily_trend': [],
            'chatbot_name': 'テストボット',
            'dashboard_url': 'https://example.com',
            'settings_url': 'https://example.com/settings',
            'unsubscribe_url': 'https://example.com/unsubscribe',
            'current_year': 2025,
        }

        html = render_to_string('emails/weekly_leads_report.html', context)

        self.assertIn('田中太郎', html)
        self.assertIn('東京', html)
