"""
Weekly leads report generation service.

This service generates comprehensive weekly reports including:
- Lead summaries and metrics
- Intent breakdown
- Geographic distribution
- Daily trends
- Week-over-week comparisons
"""

import logging
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID
from collections import Counter

from django.utils import timezone
from django.db.models import Count, Avg, Sum, Q
from django.db.models.functions import TruncDate, ExtractHour

from apps.chat.models import ChatSession, ChatMessage
from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences
from apps.organizations.models import Organization
from apps.auth.models import User

logger = logging.getLogger(__name__)


class WeeklyReportService:
    """
    Service for generating weekly leads reports.

    Reports include:
    - Summary metrics (total leads, hot/warm/cold breakdown)
    - Top leads with details
    - Intent breakdown
    - Geographic distribution
    - Daily trend
    - Week-over-week comparison
    """

    def generate_report(
        self,
        org_id: UUID,
        user_id: UUID,
        chatbot_id: Optional[UUID] = None,
        week_start: Optional[date] = None
    ) -> WeeklyLeadsReport:
        """
        Generate a weekly leads report for an organization/user.

        Args:
            org_id: Organization UUID
            user_id: User UUID (report recipient)
            chatbot_id: Optional specific chatbot (None = all chatbots)
            week_start: Start date of the week (default: last week's Monday)

        Returns:
            WeeklyLeadsReport instance
        """
        # Calculate week boundaries
        if week_start is None:
            today = timezone.now().date()
            # Get last Monday
            days_since_monday = today.weekday()
            week_start = today - timedelta(days=days_since_monday + 7)

        week_end = week_start + timedelta(days=6)

        logger.info(f"Generating report for org {org_id}, week {week_start} to {week_end}")

        # Get leads for this period
        leads_qs = LeadScore.objects.filter(
            org_id=org_id,
            session_date__gte=week_start,
            session_date__lte=week_end
        ).select_related('session', 'chatbot')

        if chatbot_id:
            leads_qs = leads_qs.filter(chatbot_id=chatbot_id)

        leads = list(leads_qs.order_by('-total_score'))

        # Get sessions for this period (for total session count)
        sessions_qs = ChatSession.objects.filter(
            org_id=org_id,
            started_at__date__gte=week_start,
            started_at__date__lte=week_end
        )
        if chatbot_id:
            sessions_qs = sessions_qs.filter(chatbot_id=chatbot_id)
        total_sessions = sessions_qs.count()

        # Calculate metrics
        hot_leads = [l for l in leads if l.priority == 'hot']
        warm_leads = [l for l in leads if l.priority == 'warm']
        cold_leads = [l for l in leads if l.priority == 'cold']

        # Generate detailed report data
        report_data = {
            'top_leads': self._serialize_top_leads(leads[:20]),
            'intent_breakdown': self._get_intent_breakdown(leads),
            'geo_distribution': self._get_geo_distribution(leads),
            'device_breakdown': self._get_device_breakdown(leads),
            'daily_trend': self._get_daily_trend(leads, week_start, week_end),
            'top_questions': self._get_top_questions(leads),
            'peak_hours': self._get_peak_hours(org_id, chatbot_id, week_start, week_end),
            'avg_session_duration': self._get_avg_duration(leads),
            'avg_messages_per_session': self._get_avg_messages(leads),
            'feedback_summary': self._get_feedback_summary(leads),
            'priority_breakdown': {
                'hot': len(hot_leads),
                'warm': len(warm_leads),
                'cold': len(cold_leads),
            },
        }

        # Calculate week-over-week comparison
        comparison = self._get_week_comparison(org_id, chatbot_id, week_start, len(leads), total_sessions)

        # Create or update report
        report, created = WeeklyLeadsReport.objects.update_or_create(
            org_id=org_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            week_start=week_start,
            defaults={
                'week_end': week_end,
                'total_sessions': total_sessions,
                'total_leads': len(leads),
                'hot_leads': len(hot_leads),
                'warm_leads': len(warm_leads),
                'cold_leads': len(cold_leads),
                'leads_change_percent': comparison['leads_change_percent'],
                'sessions_change_percent': comparison['sessions_change_percent'],
                'report_data': report_data,
            }
        )

        action = "Created" if created else "Updated"
        logger.info(f"{action} report for org {org_id}, {len(leads)} leads")

        return report

    def _serialize_top_leads(self, leads: List[LeadScore]) -> List[Dict[str, Any]]:
        """Serialize top leads for report data."""
        return [
            {
                'id': str(lead.id),
                'session_id': str(lead.session_id),
                'priority': lead.priority,
                'total_score': lead.total_score,
                'engagement_score': lead.engagement_score,
                'intent_score': lead.intent_score,
                'detected_intent': lead.detected_intent,
                'key_questions': lead.key_questions[:3] if lead.key_questions else [],
                'conversation_summary': lead.conversation_summary,
                'geo_location': lead.geo_location,
                'device_type': lead.device_type,
                'source_url': lead.source_url,
                'session_date': lead.session_date.isoformat(),
                'message_count': lead.message_count,
                'duration_seconds': lead.session_duration_seconds,
                'had_positive_feedback': lead.had_positive_feedback,
                'chatbot_name': lead.chatbot.name if lead.chatbot else None,
            }
            for lead in leads
        ]

    def _get_intent_breakdown(self, leads: List[LeadScore]) -> Dict[str, int]:
        """Get breakdown of leads by detected intent."""
        intent_counts = Counter(
            lead.detected_intent for lead in leads
            if lead.detected_intent
        )
        # Sort by count descending
        return dict(sorted(intent_counts.items(), key=lambda x: x[1], reverse=True))

    def _get_geo_distribution(self, leads: List[LeadScore]) -> Dict[str, int]:
        """Get geographic distribution of leads."""
        geo_counts = Counter()
        for lead in leads:
            if lead.geo_location:
                # Extract country (last part of location string)
                parts = lead.geo_location.split(', ')
                country = parts[-1] if parts else 'Unknown'
                geo_counts[country] += 1
            else:
                geo_counts['Unknown'] += 1

        # Sort by count descending, limit to top 10
        sorted_geo = sorted(geo_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        return dict(sorted_geo)

    def _get_device_breakdown(self, leads: List[LeadScore]) -> Dict[str, int]:
        """Get breakdown by device type."""
        device_counts = Counter(
            lead.device_type or 'unknown' for lead in leads
        )
        return dict(device_counts)

    def _get_daily_trend(
        self,
        leads: List[LeadScore],
        week_start: date,
        week_end: date
    ) -> List[Dict[str, Any]]:
        """Get daily lead count trend for the week."""
        # Initialize all days with 0
        daily_counts = {}
        current = week_start
        while current <= week_end:
            daily_counts[current.isoformat()] = {
                'date': current.isoformat(),
                'total': 0,
                'hot': 0,
                'warm': 0,
                'cold': 0,
            }
            current += timedelta(days=1)

        # Count leads per day
        for lead in leads:
            day_key = lead.session_date.isoformat()
            if day_key in daily_counts:
                daily_counts[day_key]['total'] += 1
                daily_counts[day_key][lead.priority] += 1

        return list(daily_counts.values())

    def _get_top_questions(self, leads: List[LeadScore], limit: int = 10) -> List[str]:
        """Get most common questions across all leads."""
        all_questions = []
        for lead in leads:
            if lead.key_questions:
                all_questions.extend(lead.key_questions)

        # Count question frequency (simple approach - exact match)
        question_counts = Counter(all_questions)
        return [q for q, _ in question_counts.most_common(limit)]

    def _get_peak_hours(
        self,
        org_id: UUID,
        chatbot_id: Optional[UUID],
        week_start: date,
        week_end: date
    ) -> Dict[str, int]:
        """Get session distribution by hour of day."""
        sessions_qs = ChatSession.objects.filter(
            org_id=org_id,
            started_at__date__gte=week_start,
            started_at__date__lte=week_end
        )
        if chatbot_id:
            sessions_qs = sessions_qs.filter(chatbot_id=chatbot_id)

        hourly_data = sessions_qs.annotate(
            hour=ExtractHour('started_at')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour')

        # Create dict with all hours (0-23)
        result = {str(h): 0 for h in range(24)}
        for item in hourly_data:
            result[str(item['hour'])] = item['count']

        return result

    def _get_avg_duration(self, leads: List[LeadScore]) -> float:
        """Get average session duration in seconds."""
        if not leads:
            return 0.0
        durations = [l.session_duration_seconds for l in leads if l.session_duration_seconds > 0]
        return round(sum(durations) / len(durations), 1) if durations else 0.0

    def _get_avg_messages(self, leads: List[LeadScore]) -> float:
        """Get average messages per session."""
        if not leads:
            return 0.0
        message_counts = [l.message_count for l in leads if l.message_count > 0]
        return round(sum(message_counts) / len(message_counts), 1) if message_counts else 0.0

    def _get_feedback_summary(self, leads: List[LeadScore]) -> Dict[str, int]:
        """Get summary of feedback across leads."""
        positive = sum(1 for l in leads if l.had_positive_feedback)
        negative = sum(1 for l in leads if l.had_negative_feedback)
        none = len(leads) - positive - negative

        return {
            'positive': positive,
            'negative': negative,
            'none': none,
        }

    def _get_week_comparison(
        self,
        org_id: UUID,
        chatbot_id: Optional[UUID],
        week_start: date,
        current_leads: int,
        current_sessions: int
    ) -> Dict[str, float]:
        """Compare metrics with previous week."""
        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = week_start - timedelta(days=1)

        # Previous week leads
        prev_leads_qs = LeadScore.objects.filter(
            org_id=org_id,
            session_date__gte=prev_week_start,
            session_date__lte=prev_week_end
        )
        if chatbot_id:
            prev_leads_qs = prev_leads_qs.filter(chatbot_id=chatbot_id)
        prev_leads_count = prev_leads_qs.count()

        # Previous week sessions
        prev_sessions_qs = ChatSession.objects.filter(
            org_id=org_id,
            started_at__date__gte=prev_week_start,
            started_at__date__lte=prev_week_end
        )
        if chatbot_id:
            prev_sessions_qs = prev_sessions_qs.filter(chatbot_id=chatbot_id)
        prev_sessions_count = prev_sessions_qs.count()

        # Calculate percentage changes
        leads_change = self._calc_percent_change(prev_leads_count, current_leads)
        sessions_change = self._calc_percent_change(prev_sessions_count, current_sessions)

        return {
            'previous_week_leads': prev_leads_count,
            'previous_week_sessions': prev_sessions_count,
            'leads_change_percent': leads_change,
            'sessions_change_percent': sessions_change,
        }

    def _calc_percent_change(self, old_value: int, new_value: int) -> float:
        """Calculate percentage change between two values."""
        if old_value == 0:
            return 100.0 if new_value > 0 else 0.0
        return round(((new_value - old_value) / old_value) * 100, 1)

    def generate_reports_for_all_users(self, week_start: Optional[date] = None) -> int:
        """
        Generate reports for all users with weekly reports enabled.

        Args:
            week_start: Start date of the week (default: last week)

        Returns:
            Number of reports generated
        """
        preferences = ReportPreferences.objects.filter(
            weekly_report_enabled=True
        ).select_related('user', 'org')

        count = 0
        for pref in preferences:
            try:
                # Generate report for each chatbot preference
                if pref.include_chatbot_ids:
                    for chatbot_id in pref.include_chatbot_ids:
                        self.generate_report(
                            org_id=pref.org_id,
                            user_id=pref.user_id,
                            chatbot_id=chatbot_id,
                            week_start=week_start
                        )
                        count += 1
                else:
                    # Generate report for all chatbots
                    self.generate_report(
                        org_id=pref.org_id,
                        user_id=pref.user_id,
                        chatbot_id=None,
                        week_start=week_start
                    )
                    count += 1

            except Exception as e:
                logger.error(f"Error generating report for user {pref.user_id}: {e}", exc_info=True)

        logger.info(f"Generated {count} weekly reports")
        return count

    def get_report_for_user(
        self,
        user_id: UUID,
        org_id: UUID,
        chatbot_id: Optional[UUID] = None,
        week_start: Optional[date] = None
    ) -> Optional[WeeklyLeadsReport]:
        """
        Get an existing report for a user, or generate one if it doesn't exist.

        Args:
            user_id: User UUID
            org_id: Organization UUID
            chatbot_id: Optional chatbot filter
            week_start: Week start date (default: last week)

        Returns:
            WeeklyLeadsReport instance or None
        """
        if week_start is None:
            today = timezone.now().date()
            days_since_monday = today.weekday()
            week_start = today - timedelta(days=days_since_monday + 7)

        # Try to get existing report
        report = WeeklyLeadsReport.objects.filter(
            user_id=user_id,
            org_id=org_id,
            chatbot_id=chatbot_id,
            week_start=week_start
        ).first()

        if report:
            return report

        # Generate new report
        return self.generate_report(
            org_id=org_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            week_start=week_start
        )
