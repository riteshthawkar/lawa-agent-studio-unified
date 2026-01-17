"""
API views for analytics endpoints.

Endpoints:
- GET /v1/frontend/analytics/leads/ - Leads dashboard
- GET /v1/frontend/analytics/leads/<id>/ - Lead detail
- GET /v1/frontend/analytics/reports/ - Weekly reports list
- GET /v1/frontend/analytics/reports/<id>/ - Report detail
- POST /v1/frontend/analytics/reports/generate/ - Generate report manually
- GET/PUT /v1/frontend/analytics/reports/preferences/ - Report preferences
"""

import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.organization_permissions import get_user_organizations
from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences
from apps.analytics.serializers import (
    LeadScoreSerializer,
    LeadScoreListSerializer,
    WeeklyLeadsReportSerializer,
    WeeklyReportListSerializer,
    ReportPreferencesSerializer,
    GenerateReportSerializer,
)
from apps.analytics.report_service import WeeklyReportService

logger = logging.getLogger(__name__)


def get_user_org_ids(user):
    """Get list of organization IDs the user has access to."""
    orgs = get_user_organizations(user)
    return list(orgs.values_list('id', flat=True))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def leads_dashboard(request):
    """
    GET /v1/frontend/analytics/leads/

    Get leads dashboard with summary and lead list.

    Query params:
    - days: Number of days to look back (default 7, max based on tier)
    - chatbot_id: Filter by specific chatbot
    - priority: Filter by priority (hot, warm, cold)
    - intent: Filter by detected intent
    - limit: Number of leads to return (default 50, max based on tier)
    - offset: Pagination offset
    """
    try:
        from apps.organizations.models import Organization
        from apps.usage.tier_config import get_tier_features, has_feature, get_analytics_retention_days

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({
                'summary': {'total': 0, 'hot': 0, 'warm': 0, 'cold': 0},
                'leads': [],
                'intent_breakdown': [],
                'daily_trend': [],
                'tier': {'plan': 'basic', 'features': [], 'max_days': 7}
            })

        # Get organization plan
        org = Organization.objects.filter(id__in=org_ids).first()
        plan = org.plan_tier if org else 'basic'
        tier_config = get_tier_features(plan)

        # Get tier limits
        max_days = get_analytics_retention_days(plan)
        leads_per_page = tier_config.get('limits', {}).get('leads_per_page', 10)
        if leads_per_page == -1:
            leads_per_page = 100  # Unlimited = 100 for practical purposes

        # Build tier info for response
        tier_info = {
            'plan': plan,
            'max_days': max_days,
            'features': tier_config.get('features', []),
            'export_formats': tier_config.get('export_formats', []),
            'leads_per_page': leads_per_page,
        }

        # Parse query params with tier limits enforced
        requested_days = int(request.query_params.get('days', 7))
        days = min(requested_days, max_days)
        chatbot_id = request.query_params.get('chatbot_id')
        priority = request.query_params.get('priority')
        intent = request.query_params.get('intent')
        limit = min(int(request.query_params.get('limit', leads_per_page)), leads_per_page)
        offset = int(request.query_params.get('offset', 0))

        # Calculate date range
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)

        # Base queryset
        leads_qs = LeadScore.objects.filter(
            org_id__in=org_ids,
            session_date__gte=start_date,
            session_date__lte=end_date
        ).select_related('chatbot', 'session')

        # Apply filters
        if chatbot_id:
            leads_qs = leads_qs.filter(chatbot_id=chatbot_id)
        if priority:
            leads_qs = leads_qs.filter(priority=priority)
        if intent:
            leads_qs = leads_qs.filter(detected_intent=intent)

        # Get summary counts
        summary_qs = leads_qs.values('priority').annotate(count=Count('id'))
        summary = {
            'total': 0,
            'hot': 0,
            'warm': 0,
            'cold': 0,
            'period_days': days,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        }
        for item in summary_qs:
            summary[item['priority']] = item['count']
            summary['total'] += item['count']

        # Count AI-analyzed leads
        ai_analyzed_count = leads_qs.filter(llm_insights__isnull=False).count()
        summary['ai_analyzed'] = ai_analyzed_count

        # Get intent breakdown (Premium feature)
        intent_breakdown = []
        if has_feature(plan, 'leads_intent_analysis'):
            intent_breakdown = list(
                leads_qs.exclude(detected_intent__isnull=True)
                .values('detected_intent')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            )

        # Get daily trend (Premium feature)
        daily_data = {}
        if has_feature(plan, 'leads_trend_charts'):
            daily_trend = list(
                leads_qs.values('session_date', 'priority')
                .annotate(count=Count('id'))
                .order_by('session_date')
            )
            for item in daily_trend:
                date_key = item['session_date'].isoformat()
                if date_key not in daily_data:
                    daily_data[date_key] = {'date': date_key, 'total': 0, 'hot': 0, 'warm': 0, 'cold': 0}
                daily_data[date_key][item['priority']] = item['count']
                daily_data[date_key]['total'] += item['count']

        # Get geo distribution (Premium feature)
        geo_distribution = {}
        if has_feature(plan, 'leads_geo_distribution'):
            geo_distribution = dict(
                leads_qs.exclude(geo_location__isnull=True)
                .exclude(geo_location='')
                .values_list('geo_location')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            )

        # Get device breakdown (Premium feature)
        device_breakdown = {}
        if has_feature(plan, 'leads_device_breakdown'):
            device_breakdown = dict(
                leads_qs.values_list('device_type')
                .annotate(count=Count('id'))
            )

        # Get source page analysis (Premium feature)
        source_analysis = []
        if has_feature(plan, 'leads_source_analysis'):
            source_analysis = list(
                leads_qs.exclude(source_url__isnull=True)
                .exclude(source_url='')
                .values('source_url')
                .annotate(
                    count=Count('id'),
                    avg_score=Count('total_score') / Count('id')
                )
                .order_by('-count')[:10]
            )

        # Get chatbot comparison (Premium feature)
        chatbot_comparison = []
        if has_feature(plan, 'leads_chatbot_comparison'):
            chatbot_comparison = list(
                leads_qs.values('chatbot__id', 'chatbot__name')
                .annotate(
                    total=Count('id'),
                    hot=Count('id', filter=leads_qs.model.objects.filter(priority='hot').query.where),
                    avg_score=Count('total_score') / Count('id')
                )
                .order_by('-total')[:10]
            )

        # Get score distribution (Enterprise feature)
        score_distribution = []
        if has_feature(plan, 'leads_score_distribution'):
            # Create score buckets: 0-20, 21-40, 41-60, 61-80, 81-100
            from django.db.models import Case, When, Value, CharField
            score_distribution = list(
                leads_qs.annotate(
                    score_bucket=Case(
                        When(total_score__lte=20, then=Value('0-20')),
                        When(total_score__lte=40, then=Value('21-40')),
                        When(total_score__lte=60, then=Value('41-60')),
                        When(total_score__lte=80, then=Value('61-80')),
                        default=Value('81-100'),
                        output_field=CharField(),
                    )
                ).values('score_bucket').annotate(count=Count('id')).order_by('score_bucket')
            )

        # Get quality trends (Enterprise feature)
        quality_trends = []
        if has_feature(plan, 'leads_quality_trends'):
            from django.db.models import Avg, Sum
            from django.db.models.functions import Cast
            from django.db.models import FloatField
            quality_data = list(
                leads_qs.values('session_date')
                .annotate(
                    avg_score=Avg('total_score'),
                    total=Count('id'),
                    hot_count=Count('id', filter=leads_qs.model.objects.filter(priority='hot').query.where)
                )
                .order_by('session_date')
            )
            for item in quality_data:
                hot_rate = (item['hot_count'] / item['total'] * 100) if item['total'] > 0 else 0
                quality_trends.append({
                    'date': item['session_date'].isoformat(),
                    'avg_score': round(item['avg_score'] or 0, 1),
                    'hot_rate': round(hot_rate, 1)
                })

        # Get paginated leads
        leads = leads_qs.order_by('-total_score')[offset:offset + limit]

        # Determine which serializer to use based on tier
        if has_feature(plan, 'leads_detailed_view'):
            leads_data = LeadScoreListSerializer(leads, many=True).data
        else:
            # Basic view - strip out advanced fields
            leads_data = LeadScoreListSerializer(leads, many=True).data
            for lead in leads_data:
                # Remove LLM insights for basic tier
                if not has_feature(plan, 'leads_ai_insights'):
                    lead.pop('llm_insights', None)
                    lead['has_llm_insights'] = False
                    lead.pop('company_name', None)
                    lead.pop('sentiment', None)
                    lead.pop('urgency', None)
                # Remove detailed fields for basic tier
                if not has_feature(plan, 'leads_key_questions'):
                    lead.pop('key_questions', None)
                if not has_feature(plan, 'leads_conversation_summary'):
                    lead.pop('conversation_summary', None)

        return Response({
            'summary': summary,
            'leads': leads_data,
            'intent_breakdown': intent_breakdown,
            'daily_trend': list(daily_data.values()),
            'geo_distribution': geo_distribution,
            'device_breakdown': device_breakdown,
            'source_analysis': source_analysis,
            'chatbot_comparison': chatbot_comparison,
            'score_distribution': score_distribution,
            'quality_trends': quality_trends,
            'pagination': {
                'limit': limit,
                'offset': offset,
                'total': summary['total'],
                'page': (offset // limit) + 1 if limit > 0 else 1,
                'total_pages': (summary['total'] + limit - 1) // limit if limit > 0 else 1,
            },
            'tier': tier_info,
        })

    except Exception as e:
        logger.error(f"Error in leads_dashboard: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch leads data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lead_detail(request, lead_id):
    """
    GET /v1/frontend/analytics/leads/<lead_id>/

    Get detailed information about a specific lead.
    """
    try:
        org_ids = get_user_org_ids(request.user)

        lead = LeadScore.objects.select_related(
            'chatbot', 'session'
        ).prefetch_related(
            'session__messages'
        ).filter(
            id=lead_id,
            org_id__in=org_ids
        ).first()

        if not lead:
            return Response(
                {'error': 'Lead not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        data = LeadScoreSerializer(lead).data

        # Add conversation messages
        messages = lead.session.messages.all().order_by('created_at')
        data['conversation'] = [
            {
                'role': msg.role,
                'content': msg.content,
                'feedback': msg.feedback,
                'created_at': msg.created_at.isoformat(),
            }
            for msg in messages
        ]

        return Response(data)

    except Exception as e:
        logger.error(f"Error in lead_detail: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch lead details'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weekly_reports_list(request):
    """
    GET /v1/frontend/analytics/reports/

    Get list of weekly reports for the user.

    Query params:
    - chatbot_id: Filter by specific chatbot
    - limit: Number of reports to return (default 12)
    """
    try:
        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response([])

        chatbot_id = request.query_params.get('chatbot_id')
        limit = min(int(request.query_params.get('limit', 12)), 52)

        reports_qs = WeeklyLeadsReport.objects.filter(
            org_id__in=org_ids,
            user=request.user
        ).select_related('chatbot', 'org')

        if chatbot_id:
            reports_qs = reports_qs.filter(chatbot_id=chatbot_id)

        reports = reports_qs.order_by('-week_start')[:limit]
        return Response(WeeklyReportListSerializer(reports, many=True).data)

    except Exception as e:
        logger.error(f"Error in weekly_reports_list: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch reports'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weekly_report_detail(request, report_id):
    """
    GET /v1/frontend/analytics/reports/<report_id>/

    Get detailed weekly report.
    """
    try:
        org_ids = get_user_org_ids(request.user)

        report = WeeklyLeadsReport.objects.select_related(
            'chatbot', 'org'
        ).filter(
            id=report_id,
            org_id__in=org_ids
        ).first()

        if not report:
            return Response(
                {'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(WeeklyLeadsReportSerializer(report).data)

    except Exception as e:
        logger.error(f"Error in weekly_report_detail: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch report'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_report(request):
    """
    POST /v1/frontend/analytics/reports/generate/

    Manually generate a weekly report.

    Body:
    - chatbot_id: Optional specific chatbot
    - week_start: Optional week start date (must be a Monday)
    """
    try:
        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response(
                {'error': 'No organization found'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = GenerateReportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        chatbot_id = serializer.validated_data.get('chatbot_id')
        week_start = serializer.validated_data.get('week_start')

        # Use first org for now (multi-org support can be added later)
        org_id = org_ids[0]

        service = WeeklyReportService()
        report = service.generate_report(
            org_id=org_id,
            user_id=request.user.id,
            chatbot_id=chatbot_id,
            week_start=week_start
        )

        return Response(
            WeeklyLeadsReportSerializer(report).data,
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger.error(f"Error in generate_report: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to generate report'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def report_preferences(request):
    """
    GET /v1/frontend/analytics/reports/preferences/
    PUT /v1/frontend/analytics/reports/preferences/

    Get or update report preferences for the user.
    """
    try:
        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response(
                {'error': 'No organization found'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Use first org
        org_id = org_ids[0]

        if request.method == 'GET':
            pref, created = ReportPreferences.objects.get_or_create(
                user=request.user,
                org_id=org_id,
                defaults={
                    'weekly_report_enabled': True,
                    'report_day': 0,
                    'report_hour': 9,
                    'timezone': 'UTC',
                }
            )
            return Response(ReportPreferencesSerializer(pref).data)

        else:  # PUT
            pref, created = ReportPreferences.objects.get_or_create(
                user=request.user,
                org_id=org_id,
                defaults={
                    'weekly_report_enabled': True,
                    'report_day': 0,
                    'report_hour': 9,
                    'timezone': 'UTC',
                }
            )

            serializer = ReportPreferencesSerializer(pref, data=request.data, partial=True)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            serializer.save()
            return Response(serializer.data)

    except Exception as e:
        logger.error(f"Error in report_preferences: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to process preferences'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def enhanced_analytics(request):
    """
    GET /v1/frontend/analytics/enhanced/

    Get enhanced analytics including:
    - Return visitor tracking
    - Content gap analysis
    - Peak usage forecasting
    - Conversation quality metrics

    Query params:
    - days: Number of days to analyze (default 30, max 90)
    - chatbot_id: Filter by specific chatbot
    """
    try:
        from apps.analytics.enhanced_analytics import EnhancedAnalyticsService
        from apps.sites.models import Site

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({
                'return_visitors': {'total_sessions': 0, 'new_visitors': 0, 'returning_visitors': 0},
                'content_gaps': {'total_gaps_identified': 0, 'gap_questions': []},
                'peak_usage': {'peak_hours': [], 'busiest_days': []},
                'conversation_quality': {'total_sessions': 0, 'quality_score': 0}
            })

        # Parse params
        days = min(int(request.query_params.get('days', 30)), 90)
        chatbot_id = request.query_params.get('chatbot_id')

        # Get user's site IDs
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if chatbot_id:
            # Filter to sites that have this chatbot
            from apps.chatbot.models import Chatbot
            chatbot = Chatbot.objects.filter(id=chatbot_id, site_id__in=site_ids).first()
            if chatbot:
                site_ids = [chatbot.site_id]
            else:
                return Response({'error': 'Chatbot not found'}, status=status.HTTP_404_NOT_FOUND)

        if not site_ids:
            return Response({
                'return_visitors': {'total_sessions': 0, 'new_visitors': 0, 'returning_visitors': 0},
                'content_gaps': {'total_gaps_identified': 0, 'gap_questions': []},
                'peak_usage': {'peak_hours': [], 'busiest_days': []},
                'conversation_quality': {'total_sessions': 0, 'quality_score': 0}
            })

        # Get enhanced analytics
        data = EnhancedAnalyticsService.get_full_enhanced_analytics(site_ids, days)
        data['period_days'] = days

        return Response(data)

    except Exception as e:
        logger.error(f"Error in enhanced_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch enhanced analytics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def return_visitors_analytics(request):
    """
    GET /v1/frontend/analytics/return-visitors/

    Get detailed return visitor tracking data.
    """
    try:
        from apps.analytics.enhanced_analytics import EnhancedAnalyticsService
        from apps.sites.models import Site

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({'total_sessions': 0, 'new_visitors': 0, 'returning_visitors': 0})

        days = min(int(request.query_params.get('days', 30)), 90)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if not site_ids:
            return Response({'total_sessions': 0, 'new_visitors': 0, 'returning_visitors': 0})

        data = EnhancedAnalyticsService.get_return_visitor_stats(site_ids, days)
        return Response(data)

    except Exception as e:
        logger.error(f"Error in return_visitors_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch return visitor data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def content_gaps_analytics(request):
    """
    GET /v1/frontend/analytics/content-gaps/

    Get content gap analysis - questions the chatbot struggles with.
    """
    try:
        from apps.analytics.enhanced_analytics import EnhancedAnalyticsService
        from apps.sites.models import Site

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({'total_gaps_identified': 0, 'gap_questions': [], 'recommendations': []})

        days = min(int(request.query_params.get('days', 30)), 90)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if not site_ids:
            return Response({'total_gaps_identified': 0, 'gap_questions': [], 'recommendations': []})

        data = EnhancedAnalyticsService.get_content_gap_analysis(site_ids, days)
        return Response(data)

    except Exception as e:
        logger.error(f"Error in content_gaps_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch content gap data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def peak_usage_analytics(request):
    """
    GET /v1/frontend/analytics/peak-usage/

    Get peak usage forecasting and patterns.
    """
    try:
        from apps.analytics.enhanced_analytics import EnhancedAnalyticsService
        from apps.sites.models import Site

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({'peak_hours': [], 'busiest_days': [], 'trend': 'insufficient_data'})

        days = min(int(request.query_params.get('days', 30)), 90)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if not site_ids:
            return Response({'peak_hours': [], 'busiest_days': [], 'trend': 'insufficient_data'})

        data = EnhancedAnalyticsService.get_peak_usage_forecast(site_ids, days)
        return Response(data)

    except Exception as e:
        logger.error(f"Error in peak_usage_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch peak usage data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversation_quality_analytics(request):
    """
    GET /v1/frontend/analytics/conversation-quality/

    Get conversation quality metrics.
    """
    try:
        from apps.analytics.enhanced_analytics import EnhancedAnalyticsService
        from apps.sites.models import Site

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({'total_sessions': 0, 'quality_score': 0, 'distribution': []})

        days = min(int(request.query_params.get('days', 30)), 90)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if not site_ids:
            return Response({'total_sessions': 0, 'quality_score': 0, 'distribution': []})

        data = EnhancedAnalyticsService.get_conversation_quality_metrics(site_ids, days)
        return Response(data)

    except Exception as e:
        logger.error(f"Error in conversation_quality_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch conversation quality data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def leads_export(request):
    """
    GET /v1/frontend/analytics/leads/export/

    Export leads data as CSV.

    Query params:
    - days: Number of days to look back (default 7, max 90)
    - chatbot_id: Filter by specific chatbot
    - priority: Filter by priority
    - format: Export format (csv, json) - default csv
    """
    try:
        from django.http import HttpResponse
        import csv
        import json

        org_ids = get_user_org_ids(request.user)
        if not org_ids:
            return Response({'error': 'No organization found'}, status=status.HTTP_400_BAD_REQUEST)

        # Parse params
        days = min(int(request.query_params.get('days', 7)), 90)
        chatbot_id = request.query_params.get('chatbot_id')
        priority = request.query_params.get('priority')
        export_format = request.query_params.get('format', 'csv')

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)

        leads_qs = LeadScore.objects.filter(
            org_id__in=org_ids,
            session_date__gte=start_date,
            session_date__lte=end_date
        ).select_related('chatbot')

        if chatbot_id:
            leads_qs = leads_qs.filter(chatbot_id=chatbot_id)
        if priority:
            leads_qs = leads_qs.filter(priority=priority)

        leads = leads_qs.order_by('-total_score')

        if export_format == 'json':
            data = LeadScoreListSerializer(leads, many=True).data
            return Response(data)

        # CSV export
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="leads_{start_date}_{end_date}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Priority', 'Score', 'Intent', 'Questions',
            'Location', 'Device', 'Chatbot', 'Messages', 'Duration (s)'
        ])

        for lead in leads:
            writer.writerow([
                lead.session_date.isoformat(),
                lead.priority,
                lead.total_score,
                lead.detected_intent or '',
                '; '.join(lead.key_questions[:2]) if lead.key_questions else '',
                lead.geo_location or '',
                lead.device_type or '',
                lead.chatbot.name if lead.chatbot else '',
                lead.message_count,
                lead.session_duration_seconds,
            ])

        return response

    except Exception as e:
        logger.error(f"Error in leads_export: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to export leads'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
