"""
Enhanced Analytics Service

Provides additional analytics beyond the basic stats:
- Return Visitor Tracking
- Content Gap Analysis
- Peak Usage Forecasting
- Conversation Completion Metrics
"""
import logging
from datetime import timedelta
from collections import Counter
from django.db.models import (
    Count, Avg, Sum, Min, F, Q, Case, When, Value,
    IntegerField, FloatField, ExpressionWrapper, DurationField
)
from django.db.models.functions import TruncDate, ExtractHour, ExtractWeekDay
from django.utils import timezone

from apps.chat.models import ChatSession, ChatMessage

logger = logging.getLogger(__name__)


class EnhancedAnalyticsService:
    """Service for enhanced analytics features"""

    @staticmethod
    def get_return_visitor_stats(site_ids: list, days: int = 30) -> dict:
        """
        Track return visitors vs new visitors

        Uses session fingerprinting or visitor_id to identify returning users.
        """
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Get sessions in date range
        sessions = ChatSession.objects.filter(
            site_id__in=site_ids,
            created_at__gte=start_date,
            created_at__lte=end_date
        )

        total_sessions = sessions.count()
        if total_sessions == 0:
            return {
                'total_sessions': 0,
                'new_visitors': 0,
                'returning_visitors': 0,
                'return_rate': 0,
                'visitor_breakdown': []
            }

        # Group by client_ip to identify unique visitors
        # client_ip is used as visitor fingerprint
        visitor_sessions = sessions.exclude(client_ip__isnull=True).values('client_ip').annotate(
            session_count=Count('id'),
            first_visit=Min('created_at')  # Use Min instead of Avg for timestamp (Avg not supported)
        )

        total_unique_visitors = visitor_sessions.count()

        # Visitors with more than one session are returning visitors
        returning_visitors = visitor_sessions.filter(session_count__gt=1).count()
        new_visitors = total_unique_visitors - returning_visitors

        # Calculate return rate
        return_rate = (returning_visitors / total_unique_visitors * 100) if total_unique_visitors > 0 else 0

        # Get session frequency distribution
        session_frequency = Counter()
        for v in visitor_sessions:
            count = v['session_count']
            if count == 1:
                session_frequency['1 session'] += 1
            elif count <= 3:
                session_frequency['2-3 sessions'] += 1
            elif count <= 5:
                session_frequency['4-5 sessions'] += 1
            else:
                session_frequency['6+ sessions'] += 1

        visitor_breakdown = [
            {'category': k, 'count': v}
            for k, v in sorted(session_frequency.items())
        ]

        return {
            'total_sessions': total_sessions,
            'total_unique_visitors': total_unique_visitors,
            'new_visitors': new_visitors,
            'returning_visitors': returning_visitors,
            'return_rate': round(return_rate, 1),
            'visitor_breakdown': visitor_breakdown,
            'avg_sessions_per_visitor': round(total_sessions / total_unique_visitors, 2) if total_unique_visitors > 0 else 0
        }

    @staticmethod
    def get_content_gap_analysis(site_ids: list, days: int = 30) -> dict:
        """
        Identify content gaps - questions the chatbot struggles to answer

        Looks for:
        - Messages with negative feedback
        - Short responses (might indicate lack of knowledge)
        - Sessions that ended abruptly after user message
        """
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Get user messages in sessions within the date range
        user_messages = ChatMessage.objects.filter(
            session__site_id__in=site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='user'
        ).select_related('session').prefetch_related('session__messages')

        # Get assistant messages with negative feedback
        negative_feedback_messages = ChatMessage.objects.filter(
            session__site_id__in=site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='assistant',
            feedback='dislike'
        ).values_list('id', 'content', 'session_id')

        # Get the user questions that preceded disliked answers
        gap_questions = []
        processed_sessions = set()

        for msg_id, content, session_id in negative_feedback_messages:
            if session_id in processed_sessions:
                continue

            # Find the user message before this assistant message
            try:
                user_msg = ChatMessage.objects.filter(
                    session_id=session_id,
                    role='user',
                    created_at__lt=ChatMessage.objects.get(id=msg_id).created_at
                ).order_by('-created_at').first()

                if user_msg and user_msg.content:
                    gap_questions.append({
                        'question': user_msg.content[:200],
                        'response_preview': (content or '')[:100],
                        'issue_type': 'negative_feedback',
                        'session_id': str(session_id)
                    })
                    processed_sessions.add(session_id)
            except Exception:
                continue

        # Identify short/unclear responses (potential knowledge gaps)
        short_responses = ChatMessage.objects.filter(
            session__site_id__in=site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='assistant'
        ).annotate(
            content_length=Count('content')
        ).filter(content_length__lt=50)  # Very short responses

        # Count common question patterns that got negative feedback
        question_patterns = Counter()
        for gap in gap_questions[:100]:
            # Extract first few words as pattern
            words = gap['question'].lower().split()[:3]
            if words:
                pattern = ' '.join(words)
                question_patterns[pattern] += 1

        common_gap_patterns = [
            {'pattern': pattern, 'count': count}
            for pattern, count in question_patterns.most_common(10)
        ]

        return {
            'total_gaps_identified': len(gap_questions),
            'gap_questions': gap_questions[:20],  # Top 20 gap questions
            'common_gap_patterns': common_gap_patterns,
            'recommendations': EnhancedAnalyticsService._generate_gap_recommendations(gap_questions, common_gap_patterns)
        }

    @staticmethod
    def _generate_gap_recommendations(gaps: list, patterns: list) -> list:
        """Generate recommendations based on content gaps"""
        recommendations = []

        if len(gaps) > 10:
            recommendations.append({
                'type': 'training',
                'priority': 'high',
                'message': f"Consider adding more training data - {len(gaps)} questions received negative feedback"
            })

        for pattern in patterns[:3]:
            if pattern['count'] >= 3:
                recommendations.append({
                    'type': 'content',
                    'priority': 'medium',
                    'message': f"Add content covering questions starting with '{pattern['pattern']}' ({pattern['count']} occurrences)"
                })

        if not recommendations:
            recommendations.append({
                'type': 'info',
                'priority': 'low',
                'message': "No significant content gaps detected. Your chatbot is performing well!"
            })

        return recommendations

    @staticmethod
    def get_peak_usage_forecast(site_ids: list, days: int = 30) -> dict:
        """
        Analyze usage patterns and forecast peak times
        """
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Hourly distribution
        hourly_data = ChatMessage.objects.filter(
            session__site_id__in=site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='user'
        ).annotate(
            hour=ExtractHour('created_at')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour')

        hour_map = {item['hour']: item['count'] for item in hourly_data}

        # Find peak hours
        sorted_hours = sorted(hour_map.items(), key=lambda x: x[1], reverse=True)
        peak_hours = [h for h, c in sorted_hours[:3]] if sorted_hours else []
        off_peak_hours = [h for h, c in sorted_hours[-3:]] if len(sorted_hours) >= 3 else []

        # Weekly pattern
        weekly_data = ChatMessage.objects.filter(
            session__site_id__in=site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='user'
        ).annotate(
            weekday=ExtractWeekDay('created_at')
        ).values('weekday').annotate(
            count=Count('id')
        ).order_by('weekday')

        weekday_map = {item['weekday']: item['count'] for item in weekly_data}
        day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

        # Find busiest days
        sorted_days = sorted(weekday_map.items(), key=lambda x: x[1], reverse=True)
        busiest_days = [day_names[d-1] for d, c in sorted_days[:2]] if sorted_days else []

        # Calculate trend (simple linear trend)
        daily_data = ChatMessage.objects.filter(
            session__site_id__in=site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='user'
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')

        daily_counts = [item['count'] for item in daily_data]

        # Simple trend calculation (compare first half to second half)
        if len(daily_counts) >= 4:
            mid = len(daily_counts) // 2
            first_half_avg = sum(daily_counts[:mid]) / mid
            second_half_avg = sum(daily_counts[mid:]) / (len(daily_counts) - mid)
            trend_percent = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
            trend = 'increasing' if trend_percent > 5 else 'decreasing' if trend_percent < -5 else 'stable'
        else:
            trend = 'insufficient_data'
            trend_percent = 0

        # Forecast next week (simple average-based)
        avg_daily = sum(daily_counts) / len(daily_counts) if daily_counts else 0
        forecast_daily = avg_daily * (1 + trend_percent / 100) if trend_percent else avg_daily

        return {
            'peak_hours': peak_hours,
            'peak_hours_formatted': [f"{h}:00-{h+1}:00" for h in peak_hours],
            'off_peak_hours': off_peak_hours,
            'busiest_days': busiest_days,
            'trend': trend,
            'trend_percent': round(trend_percent, 1),
            'avg_daily_messages': round(avg_daily, 1),
            'forecast_daily_messages': round(forecast_daily, 1),
            'recommendations': EnhancedAnalyticsService._generate_usage_recommendations(peak_hours, busiest_days, trend)
        }

    @staticmethod
    def _generate_usage_recommendations(peak_hours: list, busiest_days: list, trend: str) -> list:
        """Generate recommendations based on usage patterns"""
        recommendations = []

        if peak_hours:
            recommendations.append({
                'type': 'staffing',
                'message': f"Peak usage occurs around {', '.join([f'{h}:00' for h in peak_hours])}. Consider having support staff available during these times."
            })

        if busiest_days:
            recommendations.append({
                'type': 'planning',
                'message': f"Busiest days are {' and '.join(busiest_days)}. Plan content updates and maintenance outside these periods."
            })

        if trend == 'increasing':
            recommendations.append({
                'type': 'capacity',
                'message': "Traffic is trending upward. Ensure your infrastructure can handle increased load."
            })
        elif trend == 'decreasing':
            recommendations.append({
                'type': 'engagement',
                'message': "Traffic is trending downward. Consider promoting your chatbot more actively."
            })

        return recommendations

    @staticmethod
    def get_conversation_quality_metrics(site_ids: list, days: int = 30) -> dict:
        """
        Detailed conversation quality analysis
        """
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        sessions = ChatSession.objects.filter(
            site_id__in=site_ids,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).annotate(
            message_count=Count('messages'),
            user_message_count=Count('messages', filter=Q(messages__role='user')),
            assistant_message_count=Count('messages', filter=Q(messages__role='assistant')),
            duration=ExpressionWrapper(
                F('last_activity') - F('created_at'),
                output_field=DurationField()
            ),
            has_feedback=Count('messages', filter=Q(messages__feedback__in=['like', 'dislike']))
        )

        total_sessions = sessions.count()

        if total_sessions == 0:
            return {
                'total_sessions': 0,
                'completion_rate': 0,
                'engagement_rate': 0,
                'avg_turns': 0,
                'quality_score': 0,
                'distribution': []
            }

        # Completion rate: sessions with > 1 exchange
        completed_sessions = sessions.filter(message_count__gt=2).count()
        completion_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0

        # Engagement rate: sessions with feedback
        engaged_sessions = sessions.filter(has_feedback__gt=0).count()
        engagement_rate = (engaged_sessions / total_sessions * 100) if total_sessions > 0 else 0

        # Average turns (exchanges)
        avg_turns = sessions.aggregate(avg=Avg('user_message_count'))['avg'] or 0

        # Quality distribution
        quality_dist = {
            'excellent': sessions.filter(message_count__gte=6, has_feedback__gt=0).count(),
            'good': sessions.filter(message_count__gte=4, message_count__lt=6).count(),
            'average': sessions.filter(message_count__gte=2, message_count__lt=4).count(),
            'poor': sessions.filter(message_count__lt=2).count()
        }

        distribution = [
            {'quality': k.title(), 'count': v, 'percentage': round(v/total_sessions*100, 1) if total_sessions > 0 else 0}
            for k, v in quality_dist.items()
        ]

        # Calculate overall quality score (0-100)
        quality_score = (
            (quality_dist['excellent'] * 100 +
             quality_dist['good'] * 75 +
             quality_dist['average'] * 50 +
             quality_dist['poor'] * 25) / total_sessions
        ) if total_sessions > 0 else 0

        return {
            'total_sessions': total_sessions,
            'completion_rate': round(completion_rate, 1),
            'engagement_rate': round(engagement_rate, 1),
            'avg_turns': round(avg_turns, 1),
            'quality_score': round(quality_score, 1),
            'distribution': distribution
        }

    @classmethod
    def get_full_enhanced_analytics(cls, site_ids: list, days: int = 30) -> dict:
        """
        Get all enhanced analytics in one call
        """
        return {
            'return_visitors': cls.get_return_visitor_stats(site_ids, days),
            'content_gaps': cls.get_content_gap_analysis(site_ids, days),
            'peak_usage': cls.get_peak_usage_forecast(site_ids, days),
            'conversation_quality': cls.get_conversation_quality_metrics(site_ids, days)
        }
