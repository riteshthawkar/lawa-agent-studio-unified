"""
Frontend-specific API endpoints for user dashboard and management
"""
from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Avg, Sum, Prefetch, Subquery, OuterRef
from django.utils import timezone
from datetime import timedelta
import logging

from apps.core.caching import CacheManager, cache_result
from apps.core.error_handlers import (
    BusinessLogicError,
    ResourceNotFoundError,
    ExternalServiceError
)
from apps.core.organization_permissions import (
    get_user_organizations,
    check_site_access,
    OrganizationAccessError,
    ResourceNotInOrganizationError
)
from apps.core.validators import (
    InputValidator,
    InputSanitizer,
    validate_pagination_params,
    validate_search_params,
    validate_ordering_param
)

from apps.sites.models import Site
from apps.indexing.models import IndexingJob, IndexedPage
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from .serializers import (
    DashboardStatsSerializer,
    SiteManagementSerializer,
    IndexingJobManagementSerializer,
    IndexingJobHistorySerializer,
    IndexingJobDetailSerializer,
    ChatbotManagementSerializer,
    UserProfileSerializer
)


logger = logging.getLogger(__name__)


class FrontendThrottle(UserRateThrottle):
    scope = 'frontend'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def dashboard_stats(request):
    """
    GET /v1/frontend/dashboard/stats/ — Get dashboard statistics

    Returns comprehensive statistics for the user's dashboard.
    Filtered by user's organizations for proper multi-tenancy.
    """
    logger.info(f"Dashboard stats request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        # Get user's organizations for proper multi-tenancy filtering
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            # User has no organizations - return empty stats
            logger.warning(f"User {request.user.id} has no organizations")
            return Response({
                'sites': {'total': 0, 'active': 0, 'recent': []},
                'indexing': {'total_jobs': 0, 'completed_jobs': 0, 'failed_jobs': 0, 'active_jobs': 0, 'success_rate': 0, 'recent': []},
                'chatbots': {'total': 0, 'active': 0},
                'chat_sessions': {'total_30_days': 0, 'active': 0},
                'usage': {'indexing_jobs_used': 0, 'indexing_jobs_limit': 1000, 'chat_sessions_used': 0, 'chat_sessions_limit': 10000, 'sites_used': 0, 'sites_limit': 100},
                'last_updated': timezone.now().isoformat()
            })

        # Get basic counts - Filtered by user's organizations
        sites_qs = Site.objects.filter(org_id__in=org_ids)
        jobs_qs = IndexingJob.objects.filter(org_id__in=org_ids)
        # Chatbot.site_id is UUIDField, not ForeignKey
        user_site_ids = sites_qs.values_list('id', flat=True)
        chatbots_qs = Chatbot.objects.filter(site_id__in=user_site_ids)

        sites_count = sites_qs.count()
        active_sites = sites_qs.filter(status='active').count()
        
        # Indexing jobs statistics
        indexing_jobs = jobs_qs
        total_jobs = indexing_jobs.count()
        completed_jobs = indexing_jobs.filter(status='completed').count()
        failed_jobs = indexing_jobs.filter(status='failed').count()
        active_jobs = indexing_jobs.filter(status__in=['queued', 'processing', 'collecting_urls', 'processing_urls']).count()
        
        # Chatbot statistics
        chatbots_count = chatbots_qs.count()
        active_chatbots = chatbots_qs.filter(status='active').count()
        
        # Chat session statistics (last 30 days) - Filtered by user's organizations
        thirty_days_ago = timezone.now() - timedelta(days=30)
        recent_sessions = ChatSession.objects.filter(org_id__in=org_ids, created_at__gte=thirty_days_ago)
        total_sessions = recent_sessions.count()
        active_sessions = recent_sessions.filter(closed_at__isnull=True).count()
        
        # Usage statistics - simplified for MVP
        usage_stats = {
            'indexing_jobs_used': total_jobs,
            'indexing_jobs_limit': 1000,  # Fixed limit for MVP
            'chat_sessions_used': total_sessions,
            'chat_sessions_limit': 10000,  # Fixed limit for MVP
            'sites_used': sites_count,
            'sites_limit': 100  # Fixed limit for MVP
        }
        
        # Recent activity
        # Note: Cannot use select_related('site') because site_id is UUIDField, not ForeignKey
        recent_jobs = indexing_jobs.order_by('-created_at')[:5]
        recent_sites = sites_qs.order_by('-created_at')[:5]
        
        stats_data = {
            'sites': {
                'total': sites_count,
                'active': active_sites,
                'recent': SiteManagementSerializer(recent_sites, many=True).data
            },
            'indexing': {
                'total_jobs': total_jobs,
                'completed_jobs': completed_jobs,
                'failed_jobs': failed_jobs,
                'active_jobs': active_jobs,
                'success_rate': round((completed_jobs / total_jobs * 100), 2) if total_jobs > 0 else 0,
                'recent': IndexingJobManagementSerializer(recent_jobs, many=True).data
            },
            'chatbots': {
                'total': chatbots_count,
                'active': active_chatbots
            },
            'chat_sessions': {
                'total_30_days': total_sessions,
                'active': active_sessions
            },
            'usage': usage_stats,
            'last_updated': timezone.now().isoformat()
        }
        
        return Response(stats_data)

    except ValueError as e:
        logger.warning(f"Invalid parameter in dashboard stats: {str(e)}")
        return Response(
            {'error': f'Invalid parameter: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.exception("Unexpected error getting dashboard stats", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def sites_management(request):
    """
    GET /v1/frontend/sites/ — Get sites management data

    Returns detailed information about all sites for management interface.
    Filtered by user's organizations for proper multi-tenancy.
    """
    logger.info(f"Sites management request from user: {request.user.id}")

    try:
        # Get user's organizations for proper multi-tenancy filtering
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            # User has no organizations - return empty list
            logger.warning(f"User {request.user.id} has no organizations")
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': [],
                'filters': {'status_choices': ['active', 'inactive']}
            })

        # Get sites - Filtered by user's organizations
        sites = Site.objects.filter(org_id__in=org_ids)

        # Apply filters with validation
        status_filter = request.GET.get('status')
        if status_filter:
            validator = InputValidator()
            status_filter = validator.validate_choice(
                status_filter,
                ['active', 'inactive'],
                field_name='status'
            )
            sites = sites.filter(status=status_filter)

        # Search with sanitization
        search = validate_search_params(request)
        if search:
            sites = sites.filter(domain__icontains=search)

        # Ordering with validation
        allowed_ordering_fields = ['domain', 'status', 'created_at', 'updated_at', 'last_indexed_at']
        ordering = validate_ordering_param(request, allowed_ordering_fields, default='-created_at')
        sites = sites.order_by(ordering)

        # Pagination with validation
        pagination = validate_pagination_params(request)
        page = pagination['page']
        page_size = pagination['page_size']
        start = (page - 1) * page_size
        end = start + page_size

        # Optimize query with subqueries to prevent N+1 in serializer
        # Note: Using subqueries instead of Count() because site_id is UUIDField, not ForeignKey
        from django.db.models import IntegerField
        from django.db.models.functions import Coalesce

        sites = sites.annotate(
            total_jobs=Coalesce(
                Subquery(
                    IndexingJob.objects.filter(site_id=OuterRef('id'))
                    .values('site_id')
                    .annotate(count=Count('id'))
                    .values('count'),
                    output_field=IntegerField()
                ),
                0
            ),
            active_jobs=Coalesce(
                Subquery(
                    IndexingJob.objects.filter(
                        site_id=OuterRef('id'),
                        status__in=['queued', 'processing', 'collecting_urls', 'processing_urls']
                    )
                    .values('site_id')
                    .annotate(count=Count('id'))
                    .values('count'),
                    output_field=IntegerField()
                ),
                0
            ),
            total_chatbots=Coalesce(
                Subquery(
                    Chatbot.objects.filter(site_id=OuterRef('id'))
                    .values('site_id')
                    .annotate(count=Count('id'))
                    .values('count'),
                    output_field=IntegerField()
                ),
                0
            )
        )

        sites_page = sites[start:end]
        total_count = sites.count()
        
        # Serialize data
        sites_data = SiteManagementSerializer(sites_page, many=True).data
        
        return Response({
            'count': total_count,
            'next': f"?page={page + 1}&page_size={page_size}" if end < total_count else None,
            'previous': f"?page={page - 1}&page_size={page_size}" if page > 1 else None,
            'results': sites_data,
            'filters': {
                'status_choices': ['active', 'inactive']
            }
        })

    except ValueError as e:
        logger.warning(f"Invalid parameter in sites management: {str(e)}")
        return Response(
            {'error': f'Invalid parameter: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.exception("Unexpected error getting sites management", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def site_detail(request, site_id):
    """
    GET /v1/frontend/sites/{site_id}/ — Get individual site details
    
    Returns detailed information about a specific site.
    Requires organization access validation.
    """
    logger.info(f"Site detail request for site {site_id} from user: {request.user.id}")
    
    try:
        from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
        
        # Validate organization access
        try:
            site = check_site_access(request.user, site_id)
        except ResourceNotInOrganizationError:
            return Response(
                {'error': 'You do not have access to this site'},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception:
            return Response(
                {'error': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Serialize site data
        site_data = SiteManagementSerializer(site).data
        
        return Response(site_data)
        
    except Exception as e:
        logger.error(f"Error getting site detail: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def indexing_jobs_management(request):
    """
    GET /v1/frontend/indexing-jobs/ — Get indexing jobs management data

    Returns detailed information about all indexing jobs for management interface.
    Filtered by user's organizations for proper multi-tenancy.
    """
    logger.info(f"Indexing jobs management request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        # Get user's organizations for proper multi-tenancy filtering
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            # User has no organizations - return empty list
            logger.warning(f"User {request.user.id} has no organizations")
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': [],
                'filters': {'status_choices': ['queued', 'processing', 'collecting_urls', 'processing_urls', 'completed', 'failed', 'cancelled']}
            })

        # Get indexing jobs - Filtered by user's organizations
        jobs = IndexingJob.objects.filter(org_id__in=org_ids)

        # Apply filters with validation
        validator = InputValidator()
        status_filter = request.GET.get('status')
        if status_filter:
            status_filter = validator.validate_choice(
                status_filter,
                ['queued', 'processing', 'collecting_urls', 'processing_urls', 'completed', 'failed', 'cancelled'],
                field_name='status'
            )
            jobs = jobs.filter(status=status_filter)

        site_filter = request.GET.get('site_id')
        if site_filter:
            site_id = validator.validate_uuid(site_filter, field_name='site_id')
            jobs = jobs.filter(site_id=site_id)

        # Search with sanitization
        search = validate_search_params(request)
        if search:
            jobs = jobs.filter(
                Q(url__icontains=search) |
                Q(error_message__icontains=search) |
                Q(external_job_id__icontains=search)
            )

        # Ordering with validation
        allowed_ordering_fields = ['created_at', 'started_at', 'completed_at', 'status', 'url']
        ordering = validate_ordering_param(request, allowed_ordering_fields, default='-created_at')
        jobs = jobs.order_by(ordering)

        # Pagination with validation
        pagination = validate_pagination_params(request)
        page = pagination['page']
        page_size = pagination['page_size']
        start = (page - 1) * page_size
        end = start + page_size

        # Get page of jobs
        # Note: Cannot use select_related('site') because site_id is UUIDField, not ForeignKey
        jobs_page = list(jobs[start:end])
        total_count = jobs.count()

        # Prefetch sites in bulk to avoid N+1 queries
        site_ids = set(job.site_id for job in jobs_page if job.site_id)
        sites_map = {}
        if site_ids:
            sites = Site.objects.filter(id__in=site_ids)
            sites_map = {str(site.id): site for site in sites}

        # Serialize data with prefetched sites
        jobs_data = IndexingJobManagementSerializer(
            jobs_page, many=True,
            context={'sites_map': sites_map}
        ).data
        
        return Response({
            'count': total_count,
            'next': f"?page={page + 1}&page_size={page_size}" if end < total_count else None,
            'previous': f"?page={page - 1}&page_size={page_size}" if page > 1 else None,
            'results': jobs_data,
            'filters': {
                'status_choices': ['queued', 'processing', 'collecting_urls', 'processing_urls', 'completed', 'failed', 'cancelled']
            }
        })

    except Exception as e:
        logger.error(f"Error getting indexing jobs management: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def site_indexing_job_history(request, site_id):
    """
    GET /v1/frontend/sites/{site_id}/indexing-jobs/history/ — Get indexing job history for a site

    Returns detailed indexing job history with filtering, pagination, and statistics.
    Includes per-job indexed page counts and error summaries.

    Query Parameters:
    - status: Filter by job status (queued, processing, completed, failed, cancelled)
    - date_from: Filter jobs created after this date (ISO format)
    - date_to: Filter jobs created before this date (ISO format)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)
    - ordering: Sort field (created_at, -created_at, completed_at, -completed_at)
    """
    logger.info(f"Job history request for site {site_id} from user: {request.user.id}")

    try:
        # Validate site access
        from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError

        try:
            site = check_site_access(request.user, site_id)
        except ResourceNotInOrganizationError:
            return Response(
                {'error': 'You do not have access to this site'},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception:
            return Response(
                {'error': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Build queryset for jobs
        jobs = IndexingJob.objects.filter(site_id=site_id)

        # Apply status filter
        validator = InputValidator()
        status_filter = request.GET.get('status')
        if status_filter:
            status_filter = validator.validate_choice(
                status_filter,
                ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running', 'completed', 'failed', 'cancelled'],
                field_name='status'
            )
            jobs = jobs.filter(status=status_filter)

        # Apply date filters
        date_from = request.GET.get('date_from')
        if date_from:
            try:
                from dateutil.parser import parse as parse_date
                date_from_parsed = parse_date(date_from)
                jobs = jobs.filter(created_at__gte=date_from_parsed)
            except (ValueError, TypeError):
                pass

        date_to = request.GET.get('date_to')
        if date_to:
            try:
                from dateutil.parser import parse as parse_date
                date_to_parsed = parse_date(date_to)
                jobs = jobs.filter(created_at__lte=date_to_parsed)
            except (ValueError, TypeError):
                pass

        # Apply ordering
        allowed_ordering = ['created_at', '-created_at', 'completed_at', '-completed_at', 'started_at', '-started_at']
        ordering = validate_ordering_param(request, ['created_at', 'completed_at', 'started_at'], default='-created_at')
        jobs = jobs.order_by(ordering)

        # Pagination
        pagination = validate_pagination_params(request)
        page = pagination['page']
        page_size = min(pagination['page_size'], 100)
        start = (page - 1) * page_size
        end = start + page_size

        total_count = jobs.count()
        jobs_page = list(jobs[start:end])

        # Get indexed page counts for each job
        job_ids = [job.id for job in jobs_page]
        page_counts = {}
        error_counts = {}
        if job_ids:
            from django.db.models import Count
            page_stats = IndexedPage.objects.filter(
                indexing_job_id__in=job_ids
            ).values('indexing_job_id').annotate(
                total=Count('id'),
                indexed=Count('id', filter=Q(status='indexed')),
                failed=Count('id', filter=Q(status='failed')),
                skipped=Count('id', filter=Q(status='skipped'))
            )
            for stat in page_stats:
                job_id = str(stat['indexing_job_id'])
                page_counts[job_id] = {
                    'total': stat['total'],
                    'indexed': stat['indexed'],
                    'failed': stat['failed'],
                    'skipped': stat['skipped']
                }

        # Serialize with context
        jobs_data = IndexingJobHistorySerializer(
            jobs_page, many=True,
            context={'page_counts': page_counts, 'site': site}
        ).data

        # Calculate overall statistics
        all_jobs = IndexingJob.objects.filter(site_id=site_id)
        stats = {
            'total_jobs': all_jobs.count(),
            'completed_jobs': all_jobs.filter(status='completed').count(),
            'failed_jobs': all_jobs.filter(status='failed').count(),
            'active_jobs': all_jobs.filter(status__in=['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']).count(),
            'cancelled_jobs': all_jobs.filter(status='cancelled').count(),
            'avg_duration_seconds': None,
            'total_pages_indexed': IndexedPage.objects.filter(site_id=site_id, status='indexed').count(),
            'total_pages_failed': IndexedPage.objects.filter(site_id=site_id, status='failed').count(),
        }

        # Calculate average duration for completed jobs
        completed_jobs = all_jobs.filter(
            status='completed',
            started_at__isnull=False,
            completed_at__isnull=False
        )
        if completed_jobs.exists():
            total_duration = 0
            count = 0
            for job in completed_jobs[:100]:  # Limit to prevent slow queries
                if job.duration:
                    total_duration += job.duration
                    count += 1
            if count > 0:
                stats['avg_duration_seconds'] = total_duration // count

        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size,
            'next': f"?page={page + 1}&page_size={page_size}" if end < total_count else None,
            'previous': f"?page={page - 1}&page_size={page_size}" if page > 1 else None,
            'results': jobs_data,
            'stats': stats,
            'filters': {
                'status_choices': ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running', 'completed', 'failed', 'cancelled']
            }
        })

    except ValueError as e:
        logger.warning(f"Invalid parameter in job history: {str(e)}")
        return Response(
            {'error': f'Invalid parameter: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error getting job history: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def indexing_job_detail_frontend(request, job_id):
    """
    GET /v1/frontend/indexing-jobs/{job_id}/ — Get detailed indexing job information

    Returns comprehensive job details including:
    - Job metadata and configuration
    - Progress information
    - Phase results (URL collection and processing)
    - Indexed pages with status breakdown
    - Error information if failed
    """
    logger.info(f"Job detail request for job {job_id} from user: {request.user.id}")

    try:
        # Get job and validate access
        from apps.core.organization_permissions import get_user_organizations

        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response(
                {'error': 'Job not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            job = IndexingJob.objects.get(id=job_id, org_id__in=org_ids)
        except IndexingJob.DoesNotExist:
            return Response(
                {'error': 'Job not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get site information
        site = None
        if job.site_id:
            try:
                site = Site.objects.get(id=job.site_id)
            except Site.DoesNotExist:
                pass

        # Get indexed pages for this job
        indexed_pages = IndexedPage.objects.filter(indexing_job_id=job.id).order_by('-processed_at', '-created_at')

        # Page statistics
        page_stats = {
            'total': indexed_pages.count(),
            'indexed': indexed_pages.filter(status='indexed').count(),
            'failed': indexed_pages.filter(status='failed').count(),
            'skipped': indexed_pages.filter(status='skipped').count(),
            'discovered': indexed_pages.filter(status='discovered').count(),
            'processing': indexed_pages.filter(status='processing').count(),
        }

        # Get sample pages (first 50)
        sample_pages = indexed_pages[:50]
        pages_data = []
        for page in sample_pages:
            pages_data.append({
                'id': str(page.id),
                'url': page.url,
                'title': page.title,
                'status': page.status,
                'content_type': page.content_type,
                'document_count': page.document_count,
                'error_message': page.error_message if page.status == 'failed' else None,
                'processed_at': page.processed_at.isoformat() if page.processed_at else None
            })

        # Build response
        job_data = IndexingJobDetailSerializer(job, context={'site': site}).data
        job_data['page_stats'] = page_stats
        job_data['sample_pages'] = pages_data
        job_data['has_more_pages'] = page_stats['total'] > 50

        return Response(job_data)

    except Exception as e:
        logger.error(f"Error getting job detail: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def retry_indexing_job(request, job_id):
    """
    POST /v1/frontend/indexing-jobs/{job_id}/retry/ — Retry a failed indexing job

    Creates a new indexing job with the same parameters as the failed job.
    Only works for jobs with status 'failed' or 'cancelled'.
    """
    logger.info(f"Retry job request for job {job_id} from user: {request.user.id}")

    try:
        # Get job and validate access
        from apps.core.organization_permissions import get_user_organizations

        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response(
                {'error': 'Job not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            job = IndexingJob.objects.get(id=job_id, org_id__in=org_ids)
        except IndexingJob.DoesNotExist:
            return Response(
                {'error': 'Job not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate job status
        if job.status not in ['failed', 'cancelled']:
            return Response(
                {'error': f'Cannot retry job with status "{job.status}". Only failed or cancelled jobs can be retried.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get site
        try:
            site = Site.objects.get(id=job.site_id)
        except Site.DoesNotExist:
            return Response(
                {'error': 'Associated site not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Create new indexing job with same parameters
        from apps.indexing.services import IndexingService

        indexing_service = IndexingService()
        new_job = indexing_service.create_indexing_job(
            site=site,
            params={
                'url': job.url,
                'max_pages': job.max_pages,
            },
            user_id=request.user.id,
            callback_url=job.callback_url
        )

        return Response({
            'message': 'Indexing job retry initiated successfully',
            'original_job_id': str(job.id),
            'new_job_id': str(new_job.id),
            'new_job': IndexingJobHistorySerializer(new_job).data
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error retrying job: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def chatbots_management(request):
    """
    GET /v1/frontend/chatbots/ — Get chatbots management data

    Returns detailed information about all chatbots for management interface.
    Filtered by user's organizations for proper multi-tenancy.
    """
    logger.info(f"Chatbots management request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        # Get user's organizations for proper multi-tenancy filtering
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            # User has no organizations - return empty list
            logger.warning(f"User {request.user.id} has no organizations")
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': [],
                'filters': {'status_choices': ['active', 'inactive']}
            })

        # Get chatbots - Filtered by user's organizations
        # Note: Chatbot.site_id is UUIDField, not ForeignKey, so we need to get site IDs first
        user_site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
        chatbots = Chatbot.objects.filter(site_id__in=user_site_ids)

        # Apply filters with validation
        validator = InputValidator()
        status_filter = request.GET.get('status')
        if status_filter:
            status_filter = validator.validate_choice(
                status_filter,
                ['active', 'inactive'],
                field_name='status'
            )
            chatbots = chatbots.filter(status=status_filter)

        site_filter = request.GET.get('site_id')
        if site_filter:
            site_id = validator.validate_uuid(site_filter, field_name='site_id')
            chatbots = chatbots.filter(site_id=site_id)

        # Search with sanitization
        search = validate_search_params(request)
        if search:
            chatbots = chatbots.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )

        # Ordering with validation
        allowed_ordering_fields = ['name', 'status', 'created_at', 'updated_at']
        ordering = validate_ordering_param(request, allowed_ordering_fields, default='-created_at')
        chatbots = chatbots.order_by(ordering)

        # Pagination with validation
        pagination = validate_pagination_params(request)
        page = pagination['page']
        page_size = pagination['page_size']
        start = (page - 1) * page_size
        end = start + page_size

        # Annotate session counts to prevent N+1 queries
        # Note: Cannot use select_related('site') because site_id is UUIDField, not ForeignKey
        thirty_days_ago = timezone.now() - timedelta(days=30)
        chatbots = chatbots.annotate(
            recent_sessions_count=Count('chat_sessions', filter=Q(
                chat_sessions__created_at__gte=thirty_days_ago
            ), distinct=True)
        )

        chatbots_page = list(chatbots[start:end])
        total_count = chatbots.count()

        # Prefetch sites in bulk to avoid N+1 queries
        site_ids = set(cb.site_id for cb in chatbots_page if cb.site_id)
        sites_map = {}
        if site_ids:
            sites = Site.objects.filter(id__in=site_ids)
            sites_map = {str(site.id): site for site in sites}

        # Prefetch last activity (last session) for each chatbot to avoid N+1 queries
        chatbot_ids = [cb.id for cb in chatbots_page]
        last_sessions = {}
        if chatbot_ids:
            from django.db.models import Max
            # Get last session created_at for each chatbot
            last_session_data = ChatSession.objects.filter(
                chatbot_id__in=chatbot_ids
            ).values('chatbot_id').annotate(
                last_created=Max('created_at')
            )
            last_sessions = {str(item['chatbot_id']): item['last_created'] for item in last_session_data}

        # Serialize data with prefetched sites and last sessions
        chatbots_data = ChatbotManagementSerializer(
            chatbots_page, many=True,
            context={'sites_map': sites_map, 'last_sessions': last_sessions}
        ).data
        
        return Response({
            'count': total_count,
            'next': f"?page={page + 1}&page_size={page_size}" if end < total_count else None,
            'previous': f"?page={page - 1}&page_size={page_size}" if page > 1 else None,
            'results': chatbots_data,
            'filters': {
                'status_choices': ['active', 'inactive']
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting chatbots management: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def user_profile(request):
    """
    GET /v1/frontend/user/profile/ — Get user profile information

    Returns user profile information with usage/quota data.
    Filtered by user's organizations for proper multi-tenancy.
    """
    logger.info(f"User profile request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        # Get user's organizations for proper multi-tenancy filtering
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        # Get user's activity summary - Filtered by user's organizations
        user_jobs = IndexingJob.objects.filter(org_id__in=org_ids).count() if org_ids else 0
        user_sites = Site.objects.filter(org_id__in=org_ids).count() if org_ids else 0
        # Chatbot.site_id is UUIDField, not ForeignKey
        if org_ids:
            user_site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
            user_chatbots = Chatbot.objects.filter(site_id__in=user_site_ids).count()

            # Get chat sessions count
            from apps.chat.models import ChatSession
            user_sessions = ChatSession.objects.filter(site_id__in=user_site_ids).count()
        else:
            user_chatbots = 0
            user_sessions = 0

        # Calculate storage based on indexed documents
        # Estimate: ~5KB per document (includes embeddings and metadata)
        total_documents = 0
        if org_ids:
            from django.db.models import Sum
            total_documents = Site.objects.filter(org_id__in=org_ids).aggregate(
                total=Sum('total_documents')
            )['total'] or 0

        # Calculate storage in GB (5KB per document average)
        storage_bytes = total_documents * 5 * 1024  # 5KB per document
        storage_gb = storage_bytes / (1024 ** 3)
        storage_limit_gb = 10  # Default 10GB limit

        # Get quota/usage data for primary organization
        from apps.usage.models import Quota
        usage_data = {
            'sites': {'used': user_sites, 'limit': 100, 'percentage': min(int((user_sites / 100) * 100), 100)},
            'indexing_jobs': {'used': user_jobs, 'limit': 1000, 'percentage': min(int((user_jobs / 1000) * 100), 100)},
            'chatbots': {'used': user_chatbots, 'limit': 50, 'percentage': min(int((user_chatbots / 50) * 100), 100)},
            'chat_sessions': {'used': user_sessions, 'limit': 10000, 'percentage': min(int((user_sessions / 10000) * 100), 100)},
            'storage': {
                'used': round(storage_gb, 3),
                'limit': storage_limit_gb,
                'percentage': min(int((storage_gb / storage_limit_gb) * 100), 100) if storage_limit_gb > 0 else 0,
                'unit': 'GB',
                'documents': total_documents
            }
        }

        # Try to get actual quota if it exists
        if org_ids:
            try:
                quota = Quota.objects.filter(
                    org_id__in=org_ids,
                    period_start__lte=timezone.now(),
                    period_end__gte=timezone.now()
                ).first()

                if quota and quota.limits:
                    # Update limits from quota
                    if 'max_sites' in quota.limits:
                        usage_data['sites']['limit'] = quota.limits['max_sites']
                        usage_data['sites']['percentage'] = min(int((user_sites / quota.limits['max_sites']) * 100), 100) if quota.limits['max_sites'] > 0 else 0

                    if 'max_jobs' in quota.limits:
                        usage_data['indexing_jobs']['limit'] = quota.limits['max_jobs']
                        usage_data['indexing_jobs']['percentage'] = min(int((user_jobs / quota.limits['max_jobs']) * 100), 100) if quota.limits['max_jobs'] > 0 else 0

                    if 'max_chatbots' in quota.limits:
                        usage_data['chatbots']['limit'] = quota.limits['max_chatbots']
                        usage_data['chatbots']['percentage'] = min(int((user_chatbots / quota.limits['max_chatbots']) * 100), 100) if quota.limits['max_chatbots'] > 0 else 0

                    if 'max_sessions' in quota.limits:
                        usage_data['chat_sessions']['limit'] = quota.limits['max_sessions']
                        usage_data['chat_sessions']['percentage'] = min(int((user_sessions / quota.limits['max_sessions']) * 100), 100) if quota.limits['max_sessions'] > 0 else 0
            except Exception as e:
                logger.warning(f"Error fetching quota: {str(e)}")
                # Continue with default limits

        # Get organization info
        organization_data = None
        if user_orgs.exists():
            primary_org = user_orgs.first()
            organization_data = {
                'id': str(primary_org.id),
                'name': primary_org.name,
                'slug': primary_org.slug,
                'plan_tier': primary_org.plan_tier,
                'status': primary_org.status
            }

        profile_data = {
            'user': {
                'id': str(getattr(request.user, 'id', 'anonymous')),
                'email': getattr(request.user, 'email', 'anonymous@example.com'),
                'first_name': getattr(request.user, 'first_name', 'Anonymous'),
                'last_name': getattr(request.user, 'last_name', 'User'),
                'name': getattr(request.user, 'name', '') or f"{getattr(request.user, 'first_name', '')} {getattr(request.user, 'last_name', '')}".strip() or 'User',
                'date_joined': getattr(request.user, 'date_joined', timezone.now()).isoformat(),
                'last_login': getattr(request.user, 'last_login', None).isoformat() if getattr(request.user, 'last_login', None) else None
            },
            'organization': organization_data,
            'activity_summary': {
                'indexing_jobs_created': user_jobs,
                'sites_managed': user_sites,
                'chatbots_created': user_chatbots,
                'chat_sessions': user_sessions
            },
            'usage': usage_data
        }

        return Response(profile_data)

    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def bulk_actions(request):
    """
    POST /v1/frontend/bulk-actions/ — Perform bulk actions on multiple resources

    Allows bulk operations on sites, indexing jobs, or chatbots.
    All resources are validated to belong to user's organizations.
    """
    logger.info(f"Bulk actions request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        # Get user's organizations for proper multi-tenancy filtering
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response(
                {'error': 'You do not belong to any organization'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Validate input parameters
        validator = InputValidator()

        action_type = request.data.get('action_type')
        if not action_type:
            return Response(
                {'error': 'action_type is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        resource_type = request.data.get('resource_type')
        if not resource_type:
            return Response(
                {'error': 'resource_type is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate resource_type
        resource_type = validator.validate_choice(
            resource_type,
            ['sites', 'indexing_jobs', 'chatbots'],
            field_name='resource_type'
        )

        # Validate resource_ids
        resource_ids = request.data.get('resource_ids', [])
        resource_ids = validator.validate_list(
            resource_ids,
            field_name='resource_ids',
            min_length=1,
            max_length=100,
            item_validator=lambda x: validator.validate_uuid(x, field_name='resource_id')
        )

        results = []

        if resource_type == 'sites':
            # Validate action_type for sites
            action_type = validator.validate_choice(
                action_type,
                ['delete', 'block'],
                field_name='action_type'
            )

            # Filter by user's organizations for security
            resources = Site.objects.filter(id__in=resource_ids, org_id__in=org_ids)

            if action_type == 'delete':
                count = resources.count()
                resources.delete()
                results.append(f"Deleted {count} sites")
            elif action_type == 'block':
                count = resources.count()
                resources.update(status='inactive')
                results.append(f"Deactivated {count} sites")

        elif resource_type == 'indexing_jobs':
            # Validate action_type for indexing jobs
            action_type = validator.validate_choice(
                action_type,
                ['cancel', 'retry'],
                field_name='action_type'
            )

            # Filter by user's organizations for security
            resources = IndexingJob.objects.filter(id__in=resource_ids, org_id__in=org_ids)

            if action_type == 'cancel':
                count = resources.filter(status__in=['queued', 'processing']).count()
                resources.filter(status__in=['queued', 'processing']).update(status='cancelled')
                results.append(f"Cancelled {count} indexing jobs")
            elif action_type == 'retry':
                count = resources.filter(status='failed').count()
                resources.filter(status='failed').update(status='queued')
                results.append(f"Retried {count} indexing jobs")

        elif resource_type == 'chatbots':
            # Validate action_type for chatbots
            action_type = validator.validate_choice(
                action_type,
                ['activate', 'deactivate'],
                field_name='action_type'
            )

            # Filter by user's organizations for security
            # Chatbot.site_id is UUIDField, not ForeignKey
            user_site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
            resources = Chatbot.objects.filter(id__in=resource_ids, site_id__in=user_site_ids)

            if action_type == 'activate':
                count = resources.filter(status='inactive').count()
                resources.filter(status='inactive').update(status='active')
                results.append(f"Activated {count} chatbots")
            elif action_type == 'deactivate':
                count = resources.count()
                resources.update(status='inactive')
                results.append(f"Deactivated {count} chatbots")
        
        return Response({
            'message': 'Bulk actions completed successfully',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error performing bulk actions: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def search_knowledge_base(request, site_id):
    """
    POST /v1/frontend/sites/{site_id}/search/ — Search the knowledge base

    Searches the indexed content for a site using semantic similarity.

    Request Body:
    - query: str (required) - Search query text
    - top_k: int (optional) - Number of results to return (1-50, default: 10)

    Returns:
    - query: Original search query
    - namespace: Pinecone namespace searched
    - results: List of matching documents with scores
    - total_results: Number of results returned
    """
    logger.info(f"Knowledge base search request for site {site_id} from user: {request.user.id}")

    try:
        # Validate site access
        from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError

        try:
            site = check_site_access(request.user, site_id)
        except ResourceNotInOrganizationError:
            return Response(
                {'error': 'You do not have access to this site'},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception:
            return Response(
                {'error': 'Site not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get request parameters
        query = request.data.get('query', '').strip()
        if not query:
            return Response(
                {'error': 'Query is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(query) > 1000:
            return Response(
                {'error': 'Query too long (max 1000 characters)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        top_k = request.data.get('top_k', 10)
        try:
            top_k = int(top_k)
            top_k = min(max(top_k, 1), 50)  # Clamp to valid range
        except (TypeError, ValueError):
            top_k = 10

        # Get the site's active namespace using the model method
        # This returns active_namespace if set, or fallback to site_{site_id}
        namespace = site.get_namespace()

        # Call the indexing service to search
        from apps.indexing.services import IndexingService
        indexing_service = IndexingService()

        try:
            result = indexing_service.search_knowledge_base(
                namespace=namespace,
                query=query,
                top_k=top_k
            )

            # Add site context to response
            result['site_id'] = str(site_id)
            result['site_domain'] = site.domain
            result['site_name'] = site.name

            return Response(result)

        except Exception as e:
            logger.error(f"Search service error: {str(e)}")
            return Response(
                {'error': f'Search service unavailable: {str(e)}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

    except Exception as e:
        logger.error(f"Error searching knowledge base: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def analytics_data(request):
    """
    GET /v1/frontend/analytics/ — Get aggregated analytics data

    Returns comprehensive analytics including:
    - Session statistics (total, avg messages, avg duration)
    - Feedback statistics (likes, dislikes, satisfaction)
    - Performance metrics (avg response time, tokens used)
    - Time-based data (daily, hourly, weekly patterns)
    - Top content by engagement

    Query Parameters:
    - site_id: Filter by specific site (optional)
    - days: Number of days to analyze (default: 30)
    """
    logger.info(f"Analytics request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        from django.db.models import (
            Count, Sum, Avg, F, Q, Case, When, Value,
            IntegerField, FloatField, DurationField, ExpressionWrapper
        )
        from django.db.models.functions import TruncDate, ExtractHour, ExtractWeekDay, Cast

        # Get user's organizations for multi-tenancy
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response({
                'total_sessions': 0,
                'total_messages': 0,
                'feedback_stats': {'total_likes': 0, 'total_dislikes': 0, 'feedback_rate': 0, 'satisfaction_score': 0},
                'session_stats': {'total_sessions': 0, 'avg_messages_per_session': 0, 'avg_session_duration': 0, 'completion_rate': 0},
                'performance_metrics': {'avg_response_time': 0, 'total_tokens_used': 0, 'cost_estimate': '0.0000'},
                'daily_data': [],
                'hourly_data': [],
                'weekly_data': [],
                'top_content': []
            })

        # Get organization's subscription plan and tier features
        from apps.usage.models import Subscription
        from apps.usage.tier_config import get_tier_features, get_analytics_retention_days
        
        # Get subscription (create default free if doesn't exist)
        subscription = None
        if org_ids:
            subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        
        plan = subscription.get_effective_plan() if subscription else 'basic'
        tier_features = get_tier_features(plan)
        
        # Get max allowed days based on tier
        max_allowed_days = get_analytics_retention_days(
            plan, 
            subscription.analytics_retention_days if subscription else None
        )

        # Parse parameters
        site_id = request.query_params.get('site_id')
        try:
            days = int(request.query_params.get('days', 30))
            # Enforce tier limits on days
            days = min(max(days, 1), max_allowed_days)
        except (ValueError, TypeError):
            days = min(30, max_allowed_days)

        # Get user's sites
        user_site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if not user_site_ids:
            return Response({
                'total_sessions': 0,
                'total_messages': 0,
                'feedback_stats': {'total_likes': 0, 'total_dislikes': 0, 'feedback_rate': 0, 'satisfaction_score': 0},
                'session_stats': {'total_sessions': 0, 'avg_messages_per_session': 0, 'avg_session_duration': 0, 'completion_rate': 0},
                'performance_metrics': {'avg_response_time': 0, 'total_tokens_used': 0, 'cost_estimate': '0.0000'},
                'daily_data': [],
                'hourly_data': [],
                'weekly_data': [],
                'top_content': [],
                # Include tier information even with no sites
                'tier': {
                    'plan': plan,
                    'max_days': max_allowed_days,
                    'features': tier_features.get('features', []),
                    'export_formats': tier_features.get('export_formats', []),
                    'top_queries_limit': tier_features.get('top_queries_limit', 5),
                }
            })

        # Filter by specific site if provided
        if site_id:
            try:
                import uuid
                site_uuid = uuid.UUID(site_id)
                if site_uuid in user_site_ids:
                    user_site_ids = [site_uuid]
                else:
                    return Response({'error': 'Site not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid site_id format'}, status=status.HTTP_400_BAD_REQUEST)

        # Date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # ---------------------------------------------------------
        # 1. Efficient Session & Message Query
        # ---------------------------------------------------------

        # Base filters
        session_filter = Q(site_id__in=user_site_ids, created_at__gte=start_date, created_at__lte=end_date)
        
        # Get session aggregates in one go
        session_aggregates = ChatSession.objects.filter(session_filter).aggregate(
            # Only count sessions that have at least one user message
            total_sessions=Count('id', filter=Q(messages__role='user'), distinct=True),
            avg_duration=Avg(
                ExpressionWrapper(
                    F('last_activity') - F('created_at'),
                    output_field=DurationField()
                )
            ),
            total_messages=Count('messages', filter=Q(messages__role='user'))
        )
        
        # Max ensure total_sessions is at least 1 if messages exist (though aggregations handle this)
        total_sessions = session_aggregates['total_sessions'] or 0
        total_messages = session_aggregates['total_messages'] or 0 # Total user queries
        
        # Calculate avg session duration in minutes
        avg_duration_seconds = session_aggregates['avg_duration'].total_seconds() if session_aggregates['avg_duration'] else 0
        avg_session_duration = avg_duration_seconds / 60 if avg_duration_seconds else 0

        # Calculate avg messages per session and completion rate
        # Need a separate query for completion rate (sessions with > 1 message) as it's hard to aggregate purely inline without subquery grouping
        # But we can optimize: fetch message counts per session is cheaper than loading objects
        
        # Optimization: Use a subquery-like annotation approach for completion rate only if needed, 
        # or just quick count of sessions having >1 message
        from django.db.models import Subquery, OuterRef
        
        # For simplicity and speed on large datasets, Avg messages per session:
        # We know total user messages and total sessions. 
        # But usually 'messages per session' includes assistant messages too in UI? 
        # Let's stick to total messages (user+assistant) for 'avg messages per session' metric if that's standard, 
        # OR usually analytics implies User Queries. Let's stick to User Queries for consistency with `total_messages`
        # above, OR execute a quick aggregate for total ALL messages.
        
        all_messages_count = ChatMessage.objects.filter(
            session__in=ChatSession.objects.filter(session_filter)
        ).count()
        
        avg_messages_per_session = (all_messages_count / total_sessions) if total_sessions > 0 else 0

        # Completion rate: Sessions with at least 1 user message and 1 assistant message? 
        # Or just > 1 message total? Let's use > 1 message total as proxy for interaction.
        # Efficient way:
        sessions_with_activity = ChatSession.objects.filter(session_filter).annotate(
            msg_count=Count('messages')
        ).filter(msg_count__gt=1).count()
        
        completion_rate = (sessions_with_activity / total_sessions * 100) if total_sessions > 0 else 0

        session_stats = {
            'total_sessions': total_sessions,
            'avg_messages_per_session': round(avg_messages_per_session, 2),
            'avg_session_duration': round(avg_session_duration, 2),
            'completion_rate': round(completion_rate, 2)
        }

        # ---------------------------------------------------------
        # 2. Feedback & Performance Metrics (Assistant Messages)
        # ---------------------------------------------------------
        
        # Aggregate on Assistant Messages
        assistant_metrics = ChatMessage.objects.filter(
            session__site_id__in=user_site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='assistant'
        ).aggregate(
            total_assistant=Count('id'),
            likes=Count('id', filter=Q(feedback='like')),
            dislikes=Count('id', filter=Q(feedback='dislike')),
            avg_latency=Avg('latency_ms'),
            total_tokens_in=Sum('tokens_in'),
            total_tokens_out=Sum('tokens_out')
        )
        
        total_assistant = assistant_metrics['total_assistant'] or 0
        likes = assistant_metrics['likes'] or 0
        dislikes = assistant_metrics['dislikes'] or 0
        total_feedback = likes + dislikes
        
        feedback_stats = {
            'total_likes': likes,
            'total_dislikes': dislikes,
            'feedback_rate': round((total_feedback / total_assistant * 100) if total_assistant > 0 else 0, 2),
            'satisfaction_score': round((likes / total_feedback * 100) if total_feedback > 0 else 0, 2)
        }
        
        # Performance
        avg_response_time = (assistant_metrics['avg_latency'] or 0) / 1000
        total_tokens = (assistant_metrics['total_tokens_in'] or 0) + (assistant_metrics['total_tokens_out'] or 0)
        input_cost = (assistant_metrics['total_tokens_in'] or 0) * 0.00003
        output_cost = (assistant_metrics['total_tokens_out'] or 0) * 0.00006
        cost_estimate = input_cost + output_cost

        performance_metrics = {
            'avg_response_time': round(avg_response_time, 2),
            'total_tokens_used': total_tokens,
            'cost_estimate': f'{cost_estimate:.4f}'
        }

        # ---------------------------------------------------------
        # 3. Time-Series Data (Daily, Hourly, Weekly)
        # ---------------------------------------------------------
        
        # Daily Data (Aggregation)
        # Using TruncDate to group by day directly in DB
        daily_counts = ChatSession.objects.filter(session_filter).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            chats=Count('id')
        ).order_by('date')
        
        # Convert to dictionary for easy lookup
        daily_map = {item['date'].strftime('%Y-%m-%d') if item['date'] else 'unknown': item['chats'] for item in daily_counts}
        
        # Fill zero days in Python
        daily_data = []
        for i in range(min(days, 30)): # Show max 30 points on graph even if range is larger, or adapt? Frontend checks 'days'.
             # Wait, logic asked for 'days' query param. If days=90, we should probably return 90 points or aggregate.
             # The UI chart usually handles it. Let's return all days in range.
             # But let's stick to the loop limit requested by 'days' parameter.
             pass 
             
        # Re-generating day list from start_date to end_date
        current_d = start_date
        # We need to ensure we cover the requested range
        # Note: 'days' param determines the window relative to now.
        date_list = []
        for i in range(days):
            d = end_date - timedelta(days=i)
            date_str = d.strftime('%Y-%m-%d')
            date_list.append(date_str)
        
        date_list.reverse() # Oldest to newest
        
        daily_data = [
            {'date': date_str, 'chats': daily_map.get(date_str, 0)}
            for date_str in date_list
        ]
        
        # Hourly Data
        hour_counts = ChatMessage.objects.filter(
            session__site_id__in=user_site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='user'
        ).annotate(
            hour=ExtractHour('created_at')
        ).values('hour').annotate(count=Count('id')).order_by('hour')

        hour_map = {item['hour']: item['count'] for item in hour_counts}
        hourly_data = [
            {'hour': hour, 'chats': hour_map.get(hour, 0), 'label': f'{hour}:00'}
            for hour in range(24)
        ]

        # Weekly Data
        weekday_counts = ChatMessage.objects.filter(
            session__site_id__in=user_site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='user'
        ).annotate(
            weekday=ExtractWeekDay('created_at')
        ).values('weekday').annotate(count=Count('id')).order_by('weekday')
        
        weekday_map = {item['weekday']: item['count'] for item in weekday_counts}
        day_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        weekly_data = []
        for day_num in range(1, 8):
            adjusted_day = day_num - 1
            weekly_data.append({
                'day': adjusted_day,
                'chats': weekday_map.get(day_num, 0),
                'label': day_names[adjusted_day]
            })

        # ---------------------------------------------------------
        # 4. Top Content (Optimized)
        # ---------------------------------------------------------
        
        # Fetch only necessary fields, limit number of scanned rows
        # We want top content by feedback. 
        # Strategy: Fetch content/feedback for messages with feedback.
        # Use values_list to minimize object creation overhead.
        
        content_qs = ChatMessage.objects.filter(
            session__site_id__in=user_site_ids,
            session__created_at__gte=start_date,
            session__created_at__lte=end_date,
            role='assistant'
        ).exclude(feedback='no_feedback').values('content', 'feedback')[:200]
        
        # Process in Python (much faster than looping models)
        content_stats = {}
        for msg in content_qs:
            raw_content = msg['content']
            if not raw_content:
                continue
            
            # Use prefix as key to aggregate similar answers
            content_key = raw_content[:100]
            
            if content_key not in content_stats:
                content_stats[content_key] = {
                    'likes': 0, 
                    'dislikes': 0, 
                    'total': 0, 
                    'content': raw_content[:200]
                }

            content_stats[content_key]['total'] += 1
            if msg['feedback'] == 'like':
                content_stats[content_key]['likes'] += 1
            elif msg['feedback'] == 'dislike':
                content_stats[content_key]['dislikes'] += 1

        # Sort
        sorted_content = sorted(
            content_stats.items(),
            key=lambda x: x[1]['likes'] / max(x[1]['total'], 1),
            reverse=True
        )[:5]

        top_content = []
        for rank, (_, stats) in enumerate(sorted_content, 1):
            avg_rating = (stats['likes'] / stats['total'] * 100) if stats['total'] > 0 else 0
            top_content.append({
                'rank': rank,
                'content': stats['content'] + '...' if len(stats['content']) >= 200 else stats['content'],
                'likes': stats['likes'],
                'dislikes': stats['dislikes'],
                'total': stats['total'],
                'avg_rating': f'{avg_rating:.1f}%'
            })


        # ---------------------------------------------------------
        # 5. Traffic Stats (New Feature)
        # ---------------------------------------------------------
        
        # Device Breakdown
        device_breakdown = ChatSession.objects.filter(session_filter).values('device_type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        device_data = []
        for item in device_breakdown:
            dtype = item['device_type'] if item['device_type'] else 'Unknown'
            # Capitalize
            dtype = dtype.title() if dtype else 'Unknown'
            device_data.append({
                'name': dtype,
                'value': item['count']
            })

        # Top Referrers
        referrer_breakdown = ChatSession.objects.filter(session_filter).exclude(
            Q(referrer__isnull=True) | Q(referrer='')
        ).values('referrer').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        top_referrers = []
        for item in referrer_breakdown:
            top_referrers.append({
                'url': item['referrer'],
                'count': item['count']
            })

        traffic_stats = {
            'device_breakdown': device_data,
            'top_referrers': top_referrers
        }

        # ---------------------------------------------------------
        # 6. Indexing Health Stats (New Feature)
        # ---------------------------------------------------------

        # Only relevant if a specific site is selected, or we can aggregate for all selected sites
        # Let's aggregate for all user_site_ids currently in scope
        
        from apps.indexing.models import IndexedPage
        
        idx_aggregates = IndexedPage.objects.filter(site_id__in=user_site_ids).aggregate(
            total=Count('id'),
            indexed=Count('id', filter=Q(status='indexed')),
            failed=Count('id', filter=Q(status='failed'))
        )
        
        idx_total = idx_aggregates['total'] or 0
        idx_indexed = idx_aggregates['indexed'] or 0
        idx_failed = idx_aggregates['failed'] or 0
        
        idx_success_rate = round((idx_indexed / idx_total * 100), 1) if idx_total > 0 else 0
        
        indexing_stats = {
            'total_pages': idx_total,
            'indexed_pages': idx_indexed,
            'failed_pages': idx_failed,
            'success_rate': idx_success_rate
        }

        # ---------------------------------------------------------
        # 7. Geo Analytics (New Feature)
        # ---------------------------------------------------------
        
        # Aggregate by country
        country_data = ChatSession.objects.filter(session_filter).exclude(
            Q(geo_country_code__isnull=True) | Q(geo_country_code='')
        ).values('geo_country_code', 'geo_country_name').annotate(
            count=Count('id')
        ).order_by('-count')[:20]
        
        geo_analytics = {
            'countries': [
                {
                    'code': item['geo_country_code'],
                    'name': item['geo_country_name'] or item['geo_country_code'],
                    'count': item['count'],
                    'percentage': round(item['count'] / total_sessions * 100, 1) if total_sessions > 0 else 0
                }
                for item in country_data
            ],
            'cities': [] # Keep cities empty for now to avoid query overhead, or implement if needed
        }
        
        # Aggregate top cities if countries exist
        if country_data:
             city_data = ChatSession.objects.filter(session_filter).exclude(
                Q(geo_city__isnull=True) | Q(geo_city='')
            ).values('geo_city', 'geo_country_code').annotate(
                count=Count('id')
            ).order_by('-count')[:10]
             
             geo_analytics['cities'] = [
                {
                    'name': item['geo_city'],
                    'country_code': item['geo_country_code'],
                    'count': item['count']
                }
                for item in city_data
             ]


        return Response({
            'total_sessions': total_sessions,
            'total_messages': total_messages, # User queries
            'feedback_stats': feedback_stats,
            'session_stats': session_stats,
            'performance_metrics': performance_metrics,
            'daily_data': daily_data,
            'hourly_data': hourly_data,
            'weekly_data': weekly_data,
            'top_content': top_content,
            'traffic_stats': traffic_stats,
            'indexing_stats': indexing_stats,
            'geo_analytics': geo_analytics,
            # Tier information for frontend
            'tier': {
                'plan': plan,
                'max_days': max_allowed_days,
                'features': tier_features.get('features', []),
                'export_formats': tier_features.get('export_formats', []),
                'top_queries_limit': tier_features.get('top_queries_limit', 5),
            }
        })

    except Exception as e:
        logger.error(f"Error getting analytics data: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def query_analytics(request):
    """
    GET /v1/frontend/analytics/queries/ — Get query analytics data

    Returns detailed analytics about user queries including:
    - Top queries by frequency
    - Query volume trends
    - Common query patterns

    Query Parameters:
    - site_id: Filter by specific site (optional)
    - chatbot_id: Filter by specific chatbot (optional)
    - days: Number of days to analyze (default: 30)
    - limit: Number of top queries to return (default: 20)
    """
    logger.info(f"Query analytics request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        from apps.chat.models import ChatMessage, ChatSession
        from collections import Counter
        import re

        # Get user's organizations for multi-tenancy
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response({
                'top_queries': [],
                'query_volume': [],
                'query_stats': {
                    'total_queries': 0,
                    'unique_queries': 0,
                    'avg_query_length': 0
                },
                'query_categories': []
            })

        # Parse parameters
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        days = int(request.query_params.get('days', 30))
        limit = min(int(request.query_params.get('limit', 20)), 50)

        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Build base filter
        base_filter = Q(session__org_id__in=org_ids, role='user', created_at__gte=start_date)
        if site_id:
            base_filter &= Q(session__site_id=site_id)
        if chatbot_id:
            base_filter &= Q(session__chatbot_id=chatbot_id)

        # Get user messages (queries) across all sessions for the org, within the date range
        user_messages = ChatMessage.objects.filter(base_filter).order_by('-created_at')

        total_queries = user_messages.count()

        if total_queries == 0:
            return Response({
                'top_queries': [],
                'query_volume': [],
                'query_stats': {
                    'total_queries': 0,
                    'unique_queries': 0,
                    'avg_query_length': 0
                },
                'query_categories': []
            })

        # Get query content for analysis
        query_contents = list(user_messages.values_list('content', flat=True)[:1000])

        # Normalize queries for counting
        def normalize_query(q):
            if not q:
                return ''
            # Lowercase and remove extra whitespace
            q = re.sub(r'\s+', ' ', q.lower().strip())
            # Remove common punctuation
            q = re.sub(r'[?!.,;:]+$', '', q)
            return q[:200]  # Limit length

        normalized_queries = [normalize_query(q) for q in query_contents if q]
        query_counter = Counter(normalized_queries)

        # Top queries
        top_queries = []
        for query, count in query_counter.most_common(limit):
            if query and len(query) > 2:
                top_queries.append({
                    'query': query[:150] + '...' if len(query) > 150 else query,
                    'count': count,
                    'percentage': round(count / total_queries * 100, 1)
                })

        # Query volume by day
        query_volume = []
        for i in range(days):
            day = end_date - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_queries = user_messages.filter(
                created_at__gte=day_start,
                created_at__lt=day_end
            ).count()

            query_volume.append({
                'date': day_start.strftime('%Y-%m-%d'),
                'queries': day_queries
            })

        query_volume.reverse()

        # Query stats
        query_lengths = [len(q) for q in query_contents if q]
        avg_query_length = sum(query_lengths) / len(query_lengths) if query_lengths else 0
        unique_queries = len(set(normalized_queries))

        query_stats = {
            'total_queries': total_queries,
            'unique_queries': unique_queries,
            'avg_query_length': round(avg_query_length, 1),
            'repeat_rate': round((1 - unique_queries / total_queries) * 100, 1) if total_queries > 0 else 0
        }

        # Query Categorization
        # Priority: Use LLM-classified category from DB. 
        # Fallback: Use simple keyword matching if category is missing.
        
        # 1. Aggregate DB categories
        db_categories = user_messages.values('query_category').annotate(
            count=Count('id')
        ).order_by('-count')
        
        category_map = Counter()
        uncategorized_queries = []
        
        for item in db_categories:
            cat = item['query_category']
            count = item['count']
            if cat:
                category_map[cat] += count
            else:
                # Capture count of uncategorized for fallback processing
                # We can't easily get the *content* of these specific messages here without another query
                # So we'll iterate through normalized_queries for fallback, but respecting the counts we already have
                pass

        # 2. Fallback: Iterate through queries that likely didn't have a category 
        # (This is an approximation since we don't map specific query strings to their specific DB rows here easily for all)
        # Better approach: Iterate the sample `normalized_queries` we already fetched, 
        # BUT only if we have very little DB category data.
        
        # Actually, a hybrid approach is best:
        # If DB has good data (most rows have category), rely on it.
        # If DB is empty of categories (legacy data), use regex.
        
        total_db_categorized = sum(category_map.values())
        coverage_ratio = total_db_categorized / total_queries if total_queries > 0 else 0
        
        if coverage_ratio < 0.5:
            # Low DB data coverage, supplement with regex on the SAMPLE we fetched
            regex_stats = Counter()
            for query in normalized_queries:
                if not query: continue
                
                # Check regex patterns
                if query.startswith('how') or 'how to' in query or 'how do' in query:
                    regex_stats['how_to'] += 1
                elif query.startswith('what') or 'what is' in query or 'what are' in query:
                    regex_stats['what_is'] += 1
                elif any(word in query for word in ['price', 'cost', 'pricing', 'pay', 'subscription', 'plan']):
                    regex_stats['pricing'] += 1
                elif any(word in query for word in ['help', 'support', 'issue', 'problem', 'error', 'bug']):
                    regex_stats['support'] += 1
                elif any(word in query for word in ['feature', 'can i', 'does it', 'capability', 'able to']):
                    regex_stats['features'] += 1
                else:
                    regex_stats['other'] += 1
            
            # Merge logic: If DB category exists, use it. If not, maybe use regex?
            # Simpler: Just use regex stats if coverage is low (legacy mode)
            # Or better: Add regex counts to 'other' or blend? 
            # Let's strictly use the DB categories if they exist, and valid regex categories.
            
            # Since we can't easily merge without row-level logic, let's just use the regex mapping 
            # to populate standard categories if they are missing from DB map.
            for cat, count in regex_stats.items():
                # Only add if we don't have this category from DB (to avoid double counting if DB uses same names)
                # But DB probably uses different names.
                # Let's just normalize the DB categories to be cleaner if needed.
                # For now, let's just present what we have.
                if cat not in category_map:
                     # Scale the sample count to total? No, normalized_queries is top 1000.
                     # Let's just use the sample counts for the fallback.
                     category_map[cat] += count
        
        # Format for response
        query_categories = [
            {'category': cat.replace('_', ' ').title(), 'count': count, 'percentage': round(count / total_queries * 100, 1)}
            for cat, count in category_map.most_common(10) # Top 10 categories
            if count > 0
        ]


        # ---------------------------------------------------------
        # Unanswered Queries (New Feature)
        # ---------------------------------------------------------
        # Identify queries where the assistant response received a 'dislike' or where query classification was 'unanswered' (if available)
        # For now, relying on explicit 'dislike' feedback on the subsequent assistant message
        
        # Subquery to find assistant messages with dislike in the same session, immediately following user query? 
        # Easier: Find user messages whose *next* message (assistant) has dislike.
        # OR: Just filter ChatMessage where role='assistant', feedback='dislike', and get the *previous* message in session.
        # But efficiently: 
        # Let's find assistant messages with dislike first
        
        # Build filter for disliked assistant messages
        dislike_filter = Q(session__org_id__in=org_ids, role='assistant', feedback='dislike', created_at__gte=start_date)
        if site_id:
            dislike_filter &= Q(session__site_id=site_id)
        if chatbot_id:
            dislike_filter &= Q(session__chatbot_id=chatbot_id)

        disliked_assistant_msgs = ChatMessage.objects.filter(dislike_filter).select_related('session').prefetch_related('feedbacks')
        
        unanswered_queries = []
        for amsg in disliked_assistant_msgs[:50]: # Limit to reasonable number
            # Find the user message before this
            # Assuming order by created_at
            prev_msg = ChatMessage.objects.filter(
                session=amsg.session,
                created_at__lt=amsg.created_at,
                role='user'
            ).order_by('-created_at').first()
            
            # Get feedback comment if exists
            # Get feedback comment if exists - COMMENT FIELD REMOVED
            feedback_comment = ''

            if prev_msg and prev_msg.content:
                 unanswered_queries.append({
                     'query': prev_msg.content,
                     'session_id': str(amsg.session.id),
                     'timestamp': prev_msg.created_at.isoformat(),
                     'feedback_comment': feedback_comment 
                 })

        return Response({
            'top_queries': top_queries,
            'query_volume': query_volume,
            'query_stats': query_stats,
            'query_categories': query_categories,
            'unanswered_queries': unanswered_queries
        })

    except Exception as e:
        logger.error(f"Error getting query analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def citation_analytics(request):
    """
    GET /v1/frontend/analytics/citations/ — Get citation analytics data

    Returns analytics about which indexed pages are most frequently cited
    in chatbot responses.

    Query Parameters:
    - site_id: Filter by specific site (optional)
    - chatbot_id: Filter by specific chatbot (optional)
    - days: Number of days to analyze (default: 30)
    - limit: Number of top cited pages to return (default: 20)
    """
    logger.info(f"Citation analytics request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        from apps.chat.models import ChatMessage, ChatSession
        from collections import Counter

        # Get user's organizations for multi-tenancy
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response({
                'top_cited_pages': [],
                'citation_stats': {
                    'total_citations': 0,
                    'unique_pages_cited': 0,
                    'avg_citations_per_response': 0,
                    'responses_with_citations': 0
                }
            })

        # Parse parameters
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        days = int(request.query_params.get('days', 30))
        limit = min(int(request.query_params.get('limit', 20)), 50)

        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Get assistant messages with citations across all sessions for the org
        assistant_messages = ChatMessage.objects.filter(
            session__org_id__in=org_ids,
            role='assistant',
            created_at__gte=start_date
        ).exclude(citations=[])

        # Apply site and chatbot filters if provided
        if site_id:
            assistant_messages = assistant_messages.filter(session__site_id=site_id)
        if chatbot_id:
            assistant_messages = assistant_messages.filter(session__chatbot_id=chatbot_id)

        # Aggregate all citations
        all_citation_urls = []
        responses_with_citations = 0

        for message in assistant_messages:
            if message.citations:
                responses_with_citations += 1
                for citation in message.citations:
                    if isinstance(citation, dict) and 'url' in citation:
                        all_citation_urls.append(citation['url'])

        total_citations = len(all_citation_urls)

        if total_citations == 0:
            return Response({
                'top_cited_pages': [],
                'citation_stats': {
                    'total_citations': 0,
                    'unique_pages_cited': 0,
                    'avg_citations_per_response': 0,
                    'responses_with_citations': 0
                }
            })

        # Count citations per URL
        url_counter = Counter(all_citation_urls)
        unique_pages = len(url_counter)

        # Get top cited pages
        top_cited_pages = []
        for url, count in url_counter.most_common(limit):
            top_cited_pages.append({
                'url': url,
                'citations': count,
                'percentage': round(count / total_citations * 100, 1)
            })

        # Calculate stats
        citation_stats = {
            'total_citations': total_citations,
            'unique_pages_cited': unique_pages,
            'avg_citations_per_response': round(total_citations / responses_with_citations, 1) if responses_with_citations > 0 else 0,
            'responses_with_citations': responses_with_citations
        }

        return Response({
            'top_cited_pages': top_cited_pages,
            'citation_stats': citation_stats
        })

    except Exception as e:
        logger.error(f"Error getting citation analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def geo_analytics(request):
    """
    GET /v1/frontend/analytics/geo/ — Get geographic distribution of sessions

    Returns geographic analytics including:
    - Sessions by country
    - Sessions by region (for top countries)
    - Geographic distribution stats

    Query Parameters:
    - site_id: Filter by specific site (optional)
    - chatbot_id: Filter by specific chatbot (optional)
    - days: Number of days to analyze (default: 30)
    - limit: Maximum countries to return (default: 20)
    """
    try:
        # Get user's organizations for multi-tenancy
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response({
                'countries': [],
                'geo_stats': {
                    'total_sessions': 0,
                    'countries_count': 0,
                    'top_country': None
                }
            })

        # Get user's sites
        user_site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))

        if not user_site_ids:
            return Response({
                'countries': [],
                'geo_stats': {
                    'total_sessions': 0,
                    'countries_count': 0,
                    'top_country': None
                }
            })

        # Parse parameters
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        days = int(request.query_params.get('days', 30))
        limit = min(int(request.query_params.get('limit', 20)), 50)

        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Get sessions across all user's sites
        sessions = ChatSession.objects.filter(
            site_id__in=user_site_ids,
            created_at__gte=start_date
        )

        # Apply site and chatbot filters if provided
        if site_id:
            sessions = sessions.filter(site_id=site_id)
        if chatbot_id:
            sessions = sessions.filter(chatbot_id=chatbot_id)

        total_sessions = sessions.count()

        if total_sessions == 0:
            return Response({
                'countries': [],
                'geo_stats': {
                    'total_sessions': 0,
                    'countries_count': 0,
                    'top_country': None
                }
            })

        # Country name mapping for common codes
        country_names = {
            'US': 'United States',
            'GB': 'United Kingdom',
            'CA': 'Canada',
            'AU': 'Australia',
            'DE': 'Germany',
            'FR': 'France',
            'IN': 'India',
            'JP': 'Japan',
            'BR': 'Brazil',
            'IT': 'Italy',
            'ES': 'Spain',
            'NL': 'Netherlands',
            'SE': 'Sweden',
            'CH': 'Switzerland',
            'SG': 'Singapore',
            'KR': 'South Korea',
            'CN': 'China',
            'RU': 'Russia',
            'MX': 'Mexico',
            'AE': 'UAE',
            'SA': 'Saudi Arabia',
            'ZA': 'South Africa',
            'PH': 'Philippines',
            'ID': 'Indonesia',
            'TH': 'Thailand',
            'MY': 'Malaysia',
            'VN': 'Vietnam',
            'PL': 'Poland',
            'AT': 'Austria',
            'BE': 'Belgium',
        }

        # Aggregate by country
        from django.db.models import Count
        country_data = sessions.exclude(
            geo_country_code__isnull=True
        ).exclude(
            geo_country_code=''
        ).values('geo_country_code', 'geo_country_name').annotate(
            count=Count('id')
        ).order_by('-count')[:limit]

        countries = []
        for item in country_data:
            code = item['geo_country_code']
            name = item['geo_country_name'] or country_names.get(code, code)
            countries.append({
                'country_code': code,
                'country_name': name,
                'sessions': item['count'],
                'percentage': round(item['count'] / total_sessions * 100, 1)
            })

        # Count sessions with geo data
        sessions_with_geo = sessions.exclude(geo_country_code__isnull=True).exclude(geo_country_code='').count()
        unique_countries = sessions.exclude(geo_country_code__isnull=True).exclude(geo_country_code='').values('geo_country_code').distinct().count()

        geo_stats = {
            'total_sessions': total_sessions,
            'sessions_with_geo': sessions_with_geo,
            'countries_count': unique_countries,
            'top_country': countries[0]['country_name'] if countries else None,
            'geo_coverage': round(sessions_with_geo / total_sessions * 100, 1) if total_sessions > 0 else 0
        }

        return Response({
            'countries': countries,
            'geo_stats': geo_stats
        })

    except Exception as e:
        logger.error(f"Error getting geo analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def feedback_details(request):
    """
    GET /v1/frontend/analytics/feedback/ — Get detailed feedback data

    Returns detailed feedback analytics including:
    - Individual feedback entries with context
    - Feedback trends over time
    - Feedback by chatbot/site

    Query Parameters:
    - site_id: Filter by specific site (optional)
    - chatbot_id: Filter by specific chatbot (optional)
    - feedback_type: Filter by 'like' or 'dislike' (optional)
    - days: Number of days to analyze (default: 30)
    - page: Page number for pagination (default: 1)
    - page_size: Items per page (default: 20, max: 50)
    """
    logger.info(f"Feedback details request from user: {getattr(request.user, 'id', 'anonymous')}")

    try:
        from apps.chat.models import ChatMessage, ChatSession, ChatFeedback

        # Get user's organizations for multi-tenancy
        user_orgs = get_user_organizations(request.user)
        org_ids = list(user_orgs.values_list('id', flat=True))

        if not org_ids:
            return Response({
                'feedback_entries': [],
                'feedback_stats': {
                    'total_feedback': 0,
                    'likes': 0,
                    'dislikes': 0,
                    'satisfaction_rate': 0,
                    'feedback_rate': 0
                },
                'feedback_trend': [],
                'pagination': {'page': 1, 'page_size': 20, 'total': 0, 'pages': 0}
            })

        # Parse parameters
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        feedback_type = request.query_params.get('feedback_type')
        days = int(request.query_params.get('days', 30))
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(50, max(1, int(request.query_params.get('page_size', 20))))

        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Build base query for sessions
        sessions = ChatSession.objects.filter(
            org_id__in=org_ids,
            created_at__gte=start_date
        )

        if site_id:
            sessions = sessions.filter(site_id=site_id)
        if chatbot_id:
            sessions = sessions.filter(chatbot_id=chatbot_id)

        session_ids = sessions.values_list('id', flat=True)

        # Get messages with feedback
        messages_with_feedback = ChatMessage.objects.filter(
            session_id__in=session_ids,
            role='assistant',
            created_at__gte=start_date
        ).exclude(feedback='no_feedback').select_related('session')

        if feedback_type:
            messages_with_feedback = messages_with_feedback.filter(feedback=feedback_type)

        messages_with_feedback = messages_with_feedback.order_by('-created_at')

        # Calculate total stats
        total_assistant_messages = ChatMessage.objects.filter(
            session_id__in=session_ids,
            role='assistant',
            created_at__gte=start_date
        ).count()

        all_feedback = ChatMessage.objects.filter(
            session_id__in=session_ids,
            role='assistant',
            created_at__gte=start_date
        ).exclude(feedback='no_feedback')

        total_feedback = all_feedback.count()
        likes = all_feedback.filter(feedback='like').count()
        dislikes = all_feedback.filter(feedback='dislike').count()

        feedback_rate = (total_feedback / total_assistant_messages * 100) if total_assistant_messages > 0 else 0
        satisfaction_rate = (likes / total_feedback * 100) if total_feedback > 0 else 0

        feedback_stats = {
            'total_feedback': total_feedback,
            'likes': likes,
            'dislikes': dislikes,
            'satisfaction_rate': round(satisfaction_rate, 1),
            'feedback_rate': round(feedback_rate, 1),
            'total_responses': total_assistant_messages
        }

        # Paginate
        total_items = messages_with_feedback.count()
        total_pages = (total_items + page_size - 1) // page_size
        offset = (page - 1) * page_size
        paginated_messages = messages_with_feedback[offset:offset + page_size]

        # Build feedback entries
        feedback_entries = []
        for msg in paginated_messages:
            # Get the user's question (previous message in session)
            user_question = ChatMessage.objects.filter(
                session_id=msg.session_id,
                role='user',
                created_at__lt=msg.created_at
            ).order_by('-created_at').first()

            # Get detailed feedback if exists
            detailed_feedback = ChatFeedback.objects.filter(message=msg).first()

            entry = {
                'id': str(msg.id),
                'feedback_type': msg.feedback,
                'response_content': msg.content[:500] + '...' if len(msg.content) > 500 else msg.content,
                'user_question': user_question.content[:200] if user_question else None,
                'created_at': msg.created_at.isoformat(),
                'session_id': str(msg.session_id),
                'chatbot_name': msg.session.chatbot.name if msg.session and msg.session.chatbot else 'Unknown',
                'site_domain': msg.session.site.domain if msg.session and msg.session.site else 'Unknown',
                'latency_ms': msg.latency_ms,
                'comment': None  # detailed_feedback.comment if detailed_feedback else None
            }
            feedback_entries.append(entry)

        # Feedback trend by day
        feedback_trend = []
        for i in range(min(days, 14)):
            day = end_date - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_likes = all_feedback.filter(
                feedback='like',
                created_at__gte=day_start,
                created_at__lt=day_end
            ).count()

            day_dislikes = all_feedback.filter(
                feedback='dislike',
                created_at__gte=day_start,
                created_at__lt=day_end
            ).count()

            feedback_trend.append({
                'date': day_start.strftime('%Y-%m-%d'),
                'likes': day_likes,
                'dislikes': day_dislikes,
                'total': day_likes + day_dislikes
            })

        feedback_trend.reverse()

        return Response({
            'feedback_entries': feedback_entries,
            'feedback_stats': feedback_stats,
            'feedback_trend': feedback_trend,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total_items,
                'pages': total_pages
            }
        })

    except Exception as e:
        logger.error(f"Error getting feedback details: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =============================================================================
# PREMIUM ANALYTICS ENDPOINTS (Premium Tier and above)
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def sentiment_analytics(request):
    """
    Get sentiment analytics for user queries (Premium tier feature).
    Uses NLTK VADER for local sentiment analysis.
    """
    try:
        org_ids = get_user_organizations(request.user)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))
        
        if not site_ids:
            return Response({'error': 'No sites found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check tier access
        from apps.usage.models import Subscription
        from apps.usage.tier_config import has_feature
        
        subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        plan = subscription.get_effective_plan() if subscription else 'free'
        
        if not has_feature(plan, 'sentiment_analysis_aggregate'):
            return Response({
                'error': 'This feature requires a Premium or Enterprise subscription',
                'required_tier': 'premium'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get parameters
        days = int(request.query_params.get('days', 30))
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        
        # Filter to specific site if provided
        if site_id:
            site_ids = [uuid.UUID(site_id)] if uuid.UUID(site_id) in site_ids else []
        
        from apps.usage.premium_analytics import get_sentiment_analytics
        result = get_sentiment_analytics(site_ids, days=days, chatbot_id=chatbot_id)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error getting sentiment analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def cost_analytics(request):
    """
    Get cost estimation analytics based on token usage (Premium tier feature).
    """
    try:
        org_ids = get_user_organizations(request.user)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))
        
        if not site_ids:
            return Response({'error': 'No sites found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check tier access
        from apps.usage.models import Subscription
        from apps.usage.tier_config import has_feature
        
        subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        plan = subscription.get_effective_plan() if subscription else 'free'
        
        if not has_feature(plan, 'token_cost_estimation'):
            return Response({
                'error': 'This feature requires a Premium or Enterprise subscription',
                'required_tier': 'premium'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get parameters
        days = int(request.query_params.get('days', 30))
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        
        if site_id:
            site_ids = [uuid.UUID(site_id)] if uuid.UUID(site_id) in site_ids else []
        
        from apps.usage.premium_analytics import get_cost_estimation
        result = get_cost_estimation(site_ids, days=days, chatbot_id=chatbot_id)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error getting cost analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def retention_analytics(request):
    """
    Get user retention metrics (Premium tier feature).
    """
    try:
        org_ids = get_user_organizations(request.user)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))
        
        if not site_ids:
            return Response({'error': 'No sites found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check tier access
        from apps.usage.models import Subscription
        from apps.usage.tier_config import has_feature
        
        subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        plan = subscription.get_effective_plan() if subscription else 'free'
        
        if not has_feature(plan, 'retention_metrics'):
            return Response({
                'error': 'This feature requires a Premium or Enterprise subscription',
                'required_tier': 'premium'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get parameters
        days = int(request.query_params.get('days', 30))
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        
        if site_id:
            site_ids = [uuid.UUID(site_id)] if uuid.UUID(site_id) in site_ids else []
        
        from apps.usage.premium_analytics import get_retention_metrics
        result = get_retention_metrics(site_ids, days=days, chatbot_id=chatbot_id)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error getting retention analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =============================================================================
# ENTERPRISE ANALYTICS ENDPOINTS (Enterprise Tier only)
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def cohort_analytics(request):
    """
    Get cohort analysis for user retention (Enterprise tier feature).
    """
    try:
        org_ids = get_user_organizations(request.user)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))
        
        if not site_ids:
            return Response({'error': 'No sites found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check tier access (Enterprise only)
        from apps.usage.models import Subscription
        from apps.usage.tier_config import has_feature
        
        subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        plan = subscription.get_effective_plan() if subscription else 'free'
        
        if not has_feature(plan, 'cohort_analysis_weekly'):
            return Response({
                'error': 'This feature requires an Enterprise subscription',
                'required_tier': 'enterprise'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get parameters
        days = int(request.query_params.get('days', 90))
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        cohort_type = request.query_params.get('cohort_type', 'weekly')
        
        if site_id:
            site_ids = [uuid.UUID(site_id)] if uuid.UUID(site_id) in site_ids else []
        
        from apps.usage.enterprise_analytics import get_cohort_analysis
        result = get_cohort_analysis(site_ids, days=days, chatbot_id=chatbot_id, cohort_type=cohort_type)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error getting cohort analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def predictive_analytics(request):
    """
    Get predictive analytics (usage peaks, churn risk, capacity) - Enterprise tier.
    """
    try:
        org_ids = get_user_organizations(request.user)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))
        
        if not site_ids:
            return Response({'error': 'No sites found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check tier access
        from apps.usage.models import Subscription
        from apps.usage.tier_config import has_feature
        
        subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        plan = subscription.get_effective_plan() if subscription else 'free'
        
        if not has_feature(plan, 'predictive_analytics_churn'):
            return Response({
                'error': 'This feature requires an Enterprise subscription',
                'required_tier': 'enterprise'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get parameters
        days = int(request.query_params.get('days', 90))
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        
        if site_id:
            site_ids = [uuid.UUID(site_id)] if uuid.UUID(site_id) in site_ids else []
        
        from apps.usage.enterprise_analytics import get_predictive_analytics
        result = get_predictive_analytics(site_ids, days=days, chatbot_id=chatbot_id)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error getting predictive analytics: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def realtime_dashboard(request):
    """
    Get real-time dashboard data (last 24h metrics) - Enterprise tier.
    """
    try:
        org_ids = get_user_organizations(request.user)
        site_ids = list(Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True))
        
        if not site_ids:
            return Response({'error': 'No sites found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check tier access
        from apps.usage.models import Subscription
        from apps.usage.tier_config import has_feature
        
        subscription = Subscription.objects.filter(organization_id__in=org_ids).first()
        plan = subscription.get_effective_plan() if subscription else 'free'
        
        if not has_feature(plan, 'realtime_dashboard'):
            return Response({
                'error': 'This feature requires an Enterprise subscription',
                'required_tier': 'enterprise'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get parameters
        site_id = request.query_params.get('site_id')
        chatbot_id = request.query_params.get('chatbot_id')
        
        if site_id:
            site_ids = [uuid.UUID(site_id)] if uuid.UUID(site_id) in site_ids else []
        
        from apps.usage.enterprise_analytics import get_realtime_dashboard_data
        result = get_realtime_dashboard_data(site_ids, chatbot_id=chatbot_id)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error getting realtime dashboard: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
