"""
Enterprise Analytics Service for Phase 4

Provides advanced analytics features for Enterprise tier:
- Cohort analysis (weekly/monthly user cohorts)
- Predictive analytics (usage peaks, churn risk)
- Real-time dashboard data
"""
import logging
from typing import Dict, List, Optional
from django.db.models import Count, Avg, Sum, F, Q
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, ExtractHour
from django.utils import timezone
from datetime import timedelta, datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


def get_cohort_analysis(site_ids: List, days: int = 90, chatbot_id=None, cohort_type: str = 'weekly') -> Dict:
    """
    Perform cohort analysis on users based on their first interaction date.
    
    Tracks user retention by grouping users into cohorts based on when they first
    started using the chatbot, then measuring return rates over time.
    """
    from apps.chat.models import ChatSession
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    # Choose truncation function based on cohort type
    trunc_func = TruncWeek if cohort_type == 'weekly' else TruncMonth
    
    # Get all sessions in date range
    sessions_qs = ChatSession.objects.filter(
        site_id__in=site_ids,
        started_at__gte=start_date,
        started_at__lte=end_date
    )
    
    if chatbot_id:
        sessions_qs = sessions_qs.filter(chatbot_id=chatbot_id)
    
    # Group sessions by client IP (user proxy) and get first session date
    # This identifies when each "user" first appeared
    user_first_sessions = {}
    user_all_sessions = defaultdict(list)
    
    for session in sessions_qs.values('client_ip', 'started_at').iterator():
        if not session['client_ip']:
            continue
        
        ip = session['client_ip']
        date = session['started_at']
        
        if ip not in user_first_sessions or date < user_first_sessions[ip]:
            user_first_sessions[ip] = date
        
        user_all_sessions[ip].append(date)
    
    # Build cohorts
    cohorts = {}
    
    for ip, first_date in user_first_sessions.items():
        # Get cohort key (week or month start)
        if cohort_type == 'weekly':
            cohort_key = first_date.strftime('%Y-W%W')
        else:
            cohort_key = first_date.strftime('%Y-%m')
        
        if cohort_key not in cohorts:
            cohorts[cohort_key] = {
                'start_date': cohort_key,
                'users': set(),
                'retention': defaultdict(set)
            }
        
        cohorts[cohort_key]['users'].add(ip)
        
        # Track retention - which periods did this user return?
        for session_date in user_all_sessions[ip]:
            # Calculate period offset from first session
            days_since = (session_date - first_date).days
            if cohort_type == 'weekly':
                period = days_since // 7
            else:
                period = days_since // 30
            
            cohorts[cohort_key]['retention'][period].add(ip)
    
    # Convert to serializable format with retention rates
    cohort_data = []
    max_periods = 12 if cohort_type == 'weekly' else 6
    
    for cohort_key in sorted(cohorts.keys())[-max_periods:]:  # Last N cohorts
        cohort = cohorts[cohort_key]
        total_users = len(cohort['users'])
        
        retention_rates = []
        for period in range(max_periods):
            retained = len(cohort['retention'].get(period, set()))
            rate = round(retained / total_users * 100, 1) if total_users else 0
            retention_rates.append({
                'period': period,
                'retained': retained,
                'rate': rate
            })
        
        cohort_data.append({
            'cohort': cohort_key,
            'total_users': total_users,
            'retention': retention_rates
        })
    
    return {
        'cohort_type': cohort_type,
        'period_days': days,
        'cohorts': cohort_data,
        'summary': {
            'total_cohorts': len(cohort_data),
            'total_users': sum(c['total_users'] for c in cohort_data),
            'avg_week1_retention': round(
                sum(c['retention'][1]['rate'] for c in cohort_data if len(c['retention']) > 1) / 
                len([c for c in cohort_data if len(c['retention']) > 1])
                if cohort_data else 0, 1
            )
        }
    }


def get_predictive_analytics(site_ids: List, days: int = 90, chatbot_id=None) -> Dict:
    """
    Generate predictive analytics including:
    - Usage peak predictions based on historical patterns
    - Churn risk indicators
    - Capacity forecasting
    
    Uses simple statistical analysis (no external AI API required).
    """
    from apps.chat.models import ChatSession, ChatMessage
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    sessions_qs = ChatSession.objects.filter(
        site_id__in=site_ids,
        started_at__gte=start_date,
        started_at__lte=end_date
    )
    
    if chatbot_id:
        sessions_qs = sessions_qs.filter(chatbot_id=chatbot_id)
    
    # Hourly usage patterns for peak prediction
    hourly_usage = sessions_qs.annotate(
        hour=ExtractHour('started_at')
    ).values('hour').annotate(
        sessions=Count('id')
    ).order_by('hour')
    
    hourly_data = {h['hour']: h['sessions'] for h in hourly_usage}
    
    # Find peak hours
    peak_hours = sorted(hourly_data.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Daily usage for trend analysis
    daily_usage = sessions_qs.annotate(
        date=TruncDate('started_at')
    ).values('date').annotate(
        sessions=Count('id')
    ).order_by('date')
    
    daily_data = list(daily_usage)
    
    # Calculate weekly averages for forecasting
    weekly_avg = []
    for i in range(0, len(daily_data), 7):
        week_data = daily_data[i:i+7]
        if week_data:
            avg = sum(d['sessions'] for d in week_data) / len(week_data)
            weekly_avg.append({
                'week': i // 7 + 1,
                'avg_daily_sessions': round(avg, 1)
            })
    
    # Simple growth rate calculation
    if len(weekly_avg) >= 2:
        recent = weekly_avg[-1]['avg_daily_sessions']
        previous = weekly_avg[-2]['avg_daily_sessions']
        growth_rate = ((recent - previous) / previous * 100) if previous else 0
    else:
        growth_rate = 0
    
    # Project next week
    current_avg = weekly_avg[-1]['avg_daily_sessions'] if weekly_avg else 0
    projected_next_week = round(current_avg * (1 + growth_rate / 100), 1)
    
    # Churn risk indicators based on engagement decline
    # Get users who were active in first half but not second half
    mid_date = start_date + timedelta(days=days // 2)
    
    first_half_users = set(
        sessions_qs.filter(started_at__lt=mid_date)
        .values_list('client_ip', flat=True)
    )
    second_half_users = set(
        sessions_qs.filter(started_at__gte=mid_date)
        .values_list('client_ip', flat=True)
    )
    
    churned = first_half_users - second_half_users
    retained = first_half_users & second_half_users
    new_users = second_half_users - first_half_users
    
    churn_rate = round(len(churned) / len(first_half_users) * 100, 1) if first_half_users else 0
    
    return {
        'peaks': {
            'peak_hours': [
                {'hour': h, 'sessions': s, 'formatted': f"{h:02d}:00"}
                for h, s in peak_hours
            ],
            'recommendation': f"Expect highest traffic between {peak_hours[0][0]:02d}:00-{(peak_hours[0][0]+1):02d}:00" if peak_hours else None
        },
        'forecast': {
            'current_avg_daily': current_avg,
            'projected_next_week': projected_next_week,
            'growth_rate_percent': round(growth_rate, 1),
            'weekly_trend': weekly_avg[-4:] if len(weekly_avg) >= 4 else weekly_avg
        },
        'churn': {
            'churn_rate_percent': churn_rate,
            'churned_users': len(churned),
            'retained_users': len(retained),
            'new_users': len(new_users),
            'risk_level': 'high' if churn_rate > 30 else ('medium' if churn_rate > 15 else 'low')
        },
        'capacity': {
            'peak_daily_sessions': max(d['sessions'] for d in daily_data) if daily_data else 0,
            'avg_daily_sessions': round(sum(d['sessions'] for d in daily_data) / len(daily_data), 1) if daily_data else 0,
            'recommendation': 'Consider capacity planning' if growth_rate > 20 else 'Current capacity appears adequate'
        }
    }


def get_realtime_dashboard_data(site_ids: List, chatbot_id=None) -> Dict:
    """
    Get real-time dashboard metrics for the last 24 hours.
    Designed for frequent polling or WebSocket updates.
    """
    from apps.chat.models import ChatSession, ChatMessage
    
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_hour = now - timedelta(hours=1)
    last_5min = now - timedelta(minutes=5)
    
    # Build base query
    sessions_qs = ChatSession.objects.filter(
        site_id__in=site_ids,
        started_at__gte=last_24h
    )
    
    if chatbot_id:
        sessions_qs = sessions_qs.filter(chatbot_id=chatbot_id)
    
    # Active sessions (last 5 minutes)
    active_sessions = sessions_qs.filter(
        last_activity__gte=last_5min
    ).count()
    
    # Sessions in last hour
    last_hour_sessions = sessions_qs.filter(started_at__gte=last_hour).count()
    
    # Last 24h sessions
    total_24h_sessions = sessions_qs.count()
    
    # Messages in last hour
    messages_last_hour = ChatMessage.objects.filter(
        session__site_id__in=site_ids,
        created_at__gte=last_hour
    )
    if chatbot_id:
        messages_last_hour = messages_last_hour.filter(session__chatbot_id=chatbot_id)
    
    message_count_hour = messages_last_hour.count()
    
    # Avg response time (last hour)
    avg_latency = messages_last_hour.filter(
        role='assistant',
        latency_ms__gt=0
    ).aggregate(avg_latency=Avg('latency_ms'))['avg_latency'] or 0
    
    # Hourly breakdown for mini chart
    hourly_breakdown = sessions_qs.annotate(
        hour=ExtractHour('started_at')
    ).values('hour').annotate(
        count=Count('id')
    ).order_by('hour')
    
    hourly_data = [{'hour': i, 'sessions': 0} for i in range(24)]
    for h in hourly_breakdown:
        hourly_data[h['hour']]['sessions'] = h['count']
    
    # Recent feedback
    recent_feedback = ChatMessage.objects.filter(
        session__site_id__in=site_ids,
        created_at__gte=last_24h,
        feedback__in=['like', 'dislike']
    ).values('feedback').annotate(count=Count('id'))
    
    feedback_stats = {f['feedback']: f['count'] for f in recent_feedback}
    
    return {
        'realtime': {
            'active_sessions': active_sessions,
            'sessions_last_hour': last_hour_sessions,
            'messages_last_hour': message_count_hour,
            'avg_response_time_ms': round(avg_latency, 0),
        },
        'last_24h': {
            'total_sessions': total_24h_sessions,
            'hourly_breakdown': hourly_data,
            'likes': feedback_stats.get('like', 0),
            'dislikes': feedback_stats.get('dislike', 0),
        },
        'status': {
            'health': 'healthy' if avg_latency < 3000 else 'degraded',
            'last_updated': now.isoformat(),
        }
    }
