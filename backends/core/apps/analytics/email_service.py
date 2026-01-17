"""
Email service for sending weekly leads reports.

This service handles:
- Rendering HTML email templates
- Sending emails via Django's email backend
- Tracking delivery status
"""

import logging
from typing import Optional
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.conf import settings

from apps.analytics.models import WeeklyLeadsReport, ReportPreferences
from apps.auth.models import User

logger = logging.getLogger(__name__)


class ReportEmailService:
    """
    Service for sending weekly leads report emails.
    """

    def __init__(self):
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@lawa.ai')
        self.dashboard_base_url = getattr(settings, 'FRONTEND_URL', 'https://app.lawa.ai')

    def send_weekly_report(
        self,
        user: User,
        report: WeeklyLeadsReport
    ) -> bool:
        """
        Send weekly leads report email to a user.

        Args:
            user: User to send the email to
            report: WeeklyLeadsReport instance

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Prepare template context
            context = self._build_email_context(user, report)

            # Render HTML template
            html_content = render_to_string('emails/weekly_leads_report.html', context)
            text_content = strip_tags(html_content)

            # Build subject line
            subject = self._build_subject(report)

            # Create and send email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=self.from_email,
                to=[user.email]
            )
            email.attach_alternative(html_content, "text/html")
            email.send()

            # Update report status
            report.email_sent = True
            report.email_sent_at = timezone.now()
            report.email_error = ''
            report.save(update_fields=['email_sent', 'email_sent_at', 'email_error'])

            logger.info(f"Weekly report email sent to {user.email} for week {report.week_start}")
            return True

        except Exception as e:
            logger.error(f"Failed to send weekly report to {user.email}: {e}", exc_info=True)

            # Update report with error
            report.email_error = str(e)[:500]
            report.save(update_fields=['email_error'])

            return False

    def _build_email_context(self, user: User, report: WeeklyLeadsReport) -> dict:
        """Build context dictionary for email template."""
        report_data = report.report_data or {}

        # Calculate change indicators
        leads_trend = 'up' if report.leads_change_percent > 0 else ('down' if report.leads_change_percent < 0 else 'flat')
        sessions_trend = 'up' if report.sessions_change_percent > 0 else ('down' if report.sessions_change_percent < 0 else 'flat')

        # Get top leads for email (limit to 5) with enhanced data
        raw_top_leads = report_data.get('top_leads', [])[:5]
        top_leads = []
        for lead in raw_top_leads:
            # Extract buying signals from llm_insights if available
            llm_insights = lead.get('llm_insights', {}) or {}
            intent_data = llm_insights.get('intent', {}) or {}
            entities = llm_insights.get('entities', {}) or {}

            enhanced_lead = {
                **lead,
                'buying_signals': intent_data.get('buying_signals', []),
                'company_name': entities.get('company_name') or lead.get('company_name'),
                'has_llm_insights': bool(llm_insights.get('analyzed_by_llm')),
            }
            top_leads.append(enhanced_lead)

        # Get intent breakdown (top 5)
        intent_breakdown = report_data.get('intent_breakdown', {})
        intent_items = list(intent_breakdown.items())[:5]

        # Calculate intent percentages
        total_with_intent = sum(intent_breakdown.values())
        intent_with_percent = [
            {
                'name': intent,
                'count': count,
                'percent': round((count / total_with_intent * 100) if total_with_intent > 0 else 0)
            }
            for intent, count in intent_items
        ]

        # Dashboard URL
        dashboard_url = f"{self.dashboard_base_url}/analytics/leads"
        if report.chatbot_id:
            dashboard_url += f"?chatbot={report.chatbot_id}"

        return {
            # User info
            'user_name': user.name or user.email.split('@')[0],
            'user_email': user.email,

            # Report period
            'week_start': report.week_start,
            'week_end': report.week_end,

            # Summary metrics
            'total_leads': report.total_leads,
            'hot_leads': report.hot_leads,
            'warm_leads': report.warm_leads,
            'cold_leads': report.cold_leads,
            'total_sessions': report.total_sessions,

            # Comparisons
            'leads_change_percent': abs(report.leads_change_percent),
            'leads_trend': leads_trend,
            'sessions_change_percent': abs(report.sessions_change_percent),
            'sessions_trend': sessions_trend,

            # Detailed data
            'top_leads': top_leads,
            'intent_breakdown': intent_with_percent,
            'geo_distribution': list(report_data.get('geo_distribution', {}).items())[:5],
            'daily_trend': report_data.get('daily_trend', []),
            'top_questions': report_data.get('top_questions', [])[:5],
            'avg_session_duration': report_data.get('avg_session_duration', 0),
            'avg_messages': report_data.get('avg_messages_per_session', 0),
            'feedback_summary': report_data.get('feedback_summary', {}),

            # Chatbot info
            'chatbot_name': report.chatbot.name if report.chatbot else 'All Chatbots',
            'org_name': report.org.name if report.org else '',

            # Links
            'dashboard_url': dashboard_url,
            'settings_url': f"{self.dashboard_base_url}/settings/reports",
            'unsubscribe_url': f"{self.dashboard_base_url}/settings/reports?unsubscribe=weekly",

            # Meta
            'current_year': timezone.now().year,
        }

    def _build_subject(self, report: WeeklyLeadsReport) -> str:
        """Build email subject line."""
        chatbot_name = report.chatbot.name if report.chatbot else "All Chatbots"

        if report.hot_leads > 0:
            return f"Weekly Leads Report: {report.hot_leads} Hot Lead{'s' if report.hot_leads > 1 else ''} This Week"
        elif report.total_leads > 0:
            return f"Weekly Leads Report: {report.total_leads} Lead{'s' if report.total_leads > 1 else ''} from {chatbot_name}"
        else:
            return f"Weekly Leads Report: {report.week_start.strftime('%b %d')} - {report.week_end.strftime('%b %d')}"

    def send_reports_for_day(self, day_of_week: int, hour: int) -> int:
        """
        Send reports to all users scheduled for this day/hour.

        Args:
            day_of_week: 0=Monday, 6=Sunday
            hour: Hour of day (0-23)

        Returns:
            Number of emails sent
        """
        # Get preferences for this schedule
        preferences = ReportPreferences.objects.filter(
            weekly_report_enabled=True,
            report_day=day_of_week,
            report_hour=hour
        ).select_related('user', 'org')

        sent_count = 0
        for pref in preferences:
            # Get the latest unsent report for this user
            reports = WeeklyLeadsReport.objects.filter(
                user=pref.user,
                org=pref.org,
                email_sent=False
            ).order_by('-week_start')

            for report in reports:
                if self.send_weekly_report(pref.user, report):
                    sent_count += 1

        logger.info(f"Sent {sent_count} scheduled report emails for day {day_of_week} hour {hour}")
        return sent_count

    def send_hot_lead_notification(
        self,
        user: User,
        lead_score: 'LeadScore'
    ) -> bool:
        """
        Send immediate notification for a hot lead.

        Args:
            user: User to notify
            lead_score: The hot lead

        Returns:
            True if sent successfully
        """
        try:
            context = {
                'user_name': user.name or user.email.split('@')[0],
                'lead': {
                    'priority': lead_score.priority,
                    'intent': lead_score.detected_intent,
                    'score': lead_score.total_score,
                    'questions': lead_score.key_questions[:3],
                    'summary': lead_score.conversation_summary,
                    'geo': lead_score.geo_location,
                    'device': lead_score.device_type,
                    'date': lead_score.session_date,
                },
                'dashboard_url': f"{self.dashboard_base_url}/analytics/leads/{lead_score.id}",
                'current_year': timezone.now().year,
            }

            html_content = render_to_string('emails/hot_lead_notification.html', context)
            text_content = strip_tags(html_content)

            email = EmailMultiAlternatives(
                subject=f"Hot Lead Alert: {lead_score.detected_intent or 'High-Intent'} Visitor",
                body=text_content,
                from_email=self.from_email,
                to=[user.email]
            )
            email.attach_alternative(html_content, "text/html")
            email.send()

            logger.info(f"Hot lead notification sent to {user.email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send hot lead notification: {e}", exc_info=True)
            return False
