from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, throttle_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from apps.core.permissions import IsServiceAuthenticated, IsServiceOrAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db.models import Q, Count, Avg
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from urllib.parse import urlparse
import logging
from apps.core.logging_config import get_logger
from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
from .models import IndexingJob, IndexedPage
from .serializers import (
    IndexingJobSerializer,
    IndexingJobListSerializer,
    IndexingJobCreateSerializer,
    IndexingJobUpdateSerializer,
    IndexedPageSerializer,
    IndexedPageListSerializer,
    IndexedPageCreateSerializer
)

logger = get_logger(__name__)
from .services import IndexingService
from apps.core.views import BaseViewSet
from apps.sites.models import Site


class IndexingJobViewSet(BaseViewSet):
    """Indexing job management"""
    queryset = IndexingJob.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'site_id']
    search_fields = ['external_job_id', 'error_message']
    ordering_fields = ['created_at', 'started_at', 'completed_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return IndexingJobCreateSerializer
        return IndexingJobSerializer

    def get_queryset(self):
        """Filter jobs by organization"""
        queryset = super().get_queryset()
        request = self.request
        
        if hasattr(request, 'org_id') and request.org_id:
            return queryset.filter(org_id=request.org_id)
            
        # Fallback to user organizations
        from apps.core.organization_permissions import get_user_organizations
        user_orgs = get_user_organizations(request.user)
        return queryset.filter(org_id__in=user_orgs.values('id'))

    def create(self, request, *args, **kwargs):
        """Create new indexing job"""
        site_id = self.kwargs.get('site_id') or request.data.get('site_id')
        if not site_id:
            return Response(
                {'error': 'Site ID required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get site and validate access
        
        # Get site and validate access
        from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
        try:
            site = check_site_access(request.user, site_id)
        except (ResourceNotInOrganizationError, Exception) as e:
            return Response(
                {'error': 'Site not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create indexing job
        # Create indexing job
        indexing_service = IndexingService()
        job = indexing_service.create_indexing_job(
            site=site,
            params=serializer.validated_data,
            user_id=request.user.id,
            callback_url=serializer.validated_data.get('callback_url')
        )
        
        return Response(
            IndexingJobSerializer(job).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry a failed or completed indexing job"""
        job = self.get_object()
        
        # Validate access
        
        # Validate access
        from apps.core.organization_permissions import check_organization_access, OrganizationAccessError
        try:
            if job.org_id:
                check_organization_access(request.user, job.org_id)
        except OrganizationAccessError:
             return Response(
                {'error': 'Job not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
            
        # Create new job with same params
        indexing_service = IndexingService()
        
        # Check if original job was a single page index (max_pages=1)
        # If so, we must use append_mode to avoid overwriting the namespace
        append_mode = job.max_pages == 1
        
        new_job = indexing_service.create_indexing_job(
            site=job.site,
            params={
                'url': job.url,
                'max_pages': job.max_pages,
            },
            user_id=request.user.id,
            callback_url=job.callback_url,
            append_mode=append_mode
        )
        
        return Response({
            'message': 'Job retry initiated',
            'old_job_id': job.id,
            'new_job_id': new_job.id
        }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_indexing_jobs(request, site_id):
    """Get indexing jobs for a specific site"""
    site = get_object_or_404(Site, id=site_id)
    
    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except (ResourceNotInOrganizationError, Exception) as e:
        return Response(
            {'error': 'Site not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    
    jobs = IndexingJob.objects.filter(site_id=site_id).order_by('-created_at')
    
    # Apply filters
    status_filter = request.GET.get('status')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    serializer = IndexingJobSerializer(jobs, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def indexing_job_detail(request, job_id):
    """Get specific indexing job details"""
    job = get_object_or_404(IndexingJob, id=job_id)
    
    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_organization_access, OrganizationAccessError
    try:
        if job.org_id:
            check_organization_access(request.user, job.org_id)
    except OrganizationAccessError:
        return Response(
            {'error': 'Job not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    
    serializer = IndexingJobSerializer(job)
    return Response(serializer.data)


# API Specification Compliant Endpoints

# Rate limiting classes
class IndexingThrottle(UserRateThrottle):
    scope = 'indexing'

class IndexingAnonThrottle(AnonRateThrottle):
    scope = 'indexing_anon'

@api_view(['GET'])
@permission_classes([IsServiceOrAuthenticated])  # Allow service token OR authenticated user
@throttle_classes([IndexingThrottle, IndexingAnonThrottle])
def tasks_list(request):
    """
    GET /tasks — List tasks according to API specification
    """
    # Get query parameters
    tenant_id = request.GET.get('tenant_id')
    site_id = request.GET.get('site_id')
    external_job_id = request.GET.get('external_job_id')
    status_filter = request.GET.get('status_filter')
    try:
        limit = int(request.GET.get('limit', 100))
    except (ValueError, TypeError):
        limit = 100
    # Validate limit to prevent abuse
    limit = min(max(1, limit), 500)  # Clamp between 1 and 500
    
    
    # Build queryset
    queryset = IndexingJob.objects.all()
    
    # Apply filters
    if tenant_id:
        queryset = queryset.filter(org_id=tenant_id)
    if site_id:
        queryset = queryset.filter(site_id=site_id)
    if external_job_id:
        queryset = queryset.filter(external_job_id=external_job_id)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    
    # Separate active and completed tasks
    active_statuses = ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']
    
    # Bug fix: Auto-cleanup stuck jobs that have been processing for too long
    # Jobs stuck in processing for > 30 minutes with no progress are considered failed
    stuck_threshold = timezone.now() - timedelta(minutes=30)
    stuck_jobs = queryset.filter(
        status__in=active_statuses,
        started_at__lt=stuck_threshold,
        urls_processed=0,
        documents_indexed=0
    )
    
    # Mark stuck jobs as failed
    for job in stuck_jobs:
        try:
            job.status = 'failed'
            job.error_message = 'Job timed out - no progress after 30 minutes'
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_message', 'completed_at'])
            logger.warning(f"Auto-marked stuck job {job.id} as failed (no progress after 30 minutes)")
        except Exception as e:
            logger.error(f"Failed to cleanup stuck job {job.id}: {e}")
    
    # Now get truly active tasks (excluding newly marked failed ones)
    active_tasks = queryset.filter(status__in=active_statuses).order_by('-created_at')[:limit]
    completed_tasks = queryset.filter(status__in=['completed', 'failed', 'cancelled']).order_by('-created_at')[:limit]
    
    # Serialize data
    active_serializer = IndexingJobListSerializer(active_tasks, many=True)
    completed_serializer = IndexingJobListSerializer(completed_tasks, many=True)
    
    return Response({
        'active_tasks': active_serializer.data,
        'completed_tasks': completed_serializer.data,
        'total_active': active_tasks.count(),
        'total_completed': completed_tasks.count()
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([IndexingThrottle])
def task_detail(request, task_id):
    """
    GET /tasks/{task_id} — Get task status according to API specification
    """
    try:
        # Get organization context
        org_id = getattr(request, 'org_id', None)
        
        # Try direct task_id lookup (External ID)
        # Using filter to allow additional checks
        qs = IndexingJob.objects.all()
        
        # Enforce Multi-tenancy
        if org_id:
            qs = qs.filter(org_id=org_id)
            
        job = qs.filter(task_id=task_id).first()
        
        # Fallback 1: Try Internal UUID
        if not job:
            try:
                if len(task_id) == 36:  # Simple check for UUID-like length
                    job = qs.filter(id=task_id).first()
            except (ValueError, TypeError):
                # Invalid UUID format, ignore and continue
                pass

        # Fallback 2: Try External Job ID
        if not job:
            job = qs.filter(external_job_id=task_id).first()

        if not job:
            raise IndexingJob.DoesNotExist

        serializer = IndexingJobSerializer(job)
        return Response(serializer.data)
    except IndexingJob.DoesNotExist:
        return Response(
            {'error': 'Task not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])  # Changed from DELETE - cancel is an action, not resource deletion
@permission_classes([IsServiceOrAuthenticated])  # Allow service token OR authenticated user
@throttle_classes([IndexingThrottle, IndexingAnonThrottle])
def cancel_task(request, task_id):
    """
    POST /tasks/{task_id}/cancel/ — Cancel task according to API specification
    """
    # Get organization context for multi-tenancy validation
    org_id = getattr(request, 'org_id', None)
    
    # Build queryset with organization filter
    qs = IndexingJob.objects.all()
    if org_id:
        qs = qs.filter(org_id=org_id)
    
    # Try to find job by task_id first
    job = qs.filter(task_id=task_id).first()
    
    # Fallback: Try by internal UUID
    if not job:
        try:
            if len(task_id) == 36:
                job = qs.filter(id=task_id).first()
        except (ValueError, TypeError):
            pass
    
    # Fallback: Try by external job ID
    if not job:
        job = qs.filter(external_job_id=task_id).first()
    
    if not job:
        return Response(
            {'error': 'Task not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check if task can be cancelled
    cancellable_statuses = ['queued', 'processing', 'collecting_urls', 'processing_urls']
    if job.status not in cancellable_statuses:
        return Response(
            {'error': f'Task cannot be cancelled (current status: {job.status})'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Cancel the task
    job.mark_cancelled()
    
    return Response({
        'message': f'Task {task_id} cancelled successfully',
        'task_id': task_id,
        'status': job.status
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([IndexingThrottle, IndexingAnonThrottle])
def health_check(request):
    """
    GET /health — Health check according to API specification
    """
    # Count active and completed tasks
    active_count = IndexingJob.objects.filter(
        status__in=['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']
    ).count()
    
    completed_count = IndexingJob.objects.filter(
        status__in=['completed', 'failed', 'cancelled']
    ).count()
    
    return Response({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'active_tasks': active_count,
        'completed_tasks': completed_count
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([IndexingThrottle, IndexingAnonThrottle])
def service_stats(request):
    """
    GET /stats — Service statistics according to API specification
    """
    # Calculate statistics
    total_tasks = IndexingJob.objects.count()
    active_tasks = IndexingJob.objects.filter(
        status__in=['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']
    ).count()
    completed_tasks = IndexingJob.objects.filter(status='completed').count()
    failed_tasks = IndexingJob.objects.filter(status='failed').count()
    
    # Calculate success rate
    total_finished = completed_tasks + failed_tasks
    success_rate = (completed_tasks / total_finished * 100) if total_finished > 0 else 0
    
    # Count by status
    by_status = {}
    for status_choice in IndexingJob._meta.get_field('status').choices:
        status_code = status_choice[0]
        count = IndexingJob.objects.filter(status=status_code).count()
        by_status[status_code] = count
    
    return Response({
        'total_tasks': total_tasks,
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'success_rate': round(success_rate, 1),
        'by_status': by_status,
        'uptime': 'N/A',  # Would need to track service start time
        'timestamp': timezone.now().isoformat()
    })


@api_view(['POST'])
@permission_classes([IsServiceOrAuthenticated])  # Service or Authenticated User
@throttle_classes([IndexingThrottle, IndexingAnonThrottle])
def start_indexing(request):
    """
    POST /index — Start indexing task according to API specification
    """
    logger = logging.getLogger(__name__)
    
    logger = logging.getLogger(__name__)
    
    # Validate input data
    serializer = IndexingJobCreateSerializer(data=request.data)
    if not serializer.is_valid():
        logger.warning(f"Invalid indexing request: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Get validated data
    data = serializer.validated_data
    
    # Additional security validation
    url = data.get('url', '')
    if not url or len(url) > 2048:  # Prevent extremely long URLs
        return Response(
            {'error': 'Invalid URL length'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate URL format
    url_validator = URLValidator()
    try:
        url_validator(url)
    except ValidationError:
        return Response(
            {'error': 'Invalid URL format'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
        
    # Resolve Site from URL (Auto-create if doesn't exist for this endpoint)
    try:
        logger.debug(
            "Indexing request received",
            extra={
                'payload': request.data,
                'payload_type': type(request.data).__name__,
                'user_id': str(request.user.id) if request.user.is_authenticated else None
            }
        )
        domain = urlparse(url).netloc
        # Remove port if present
        if ':' in domain:
            domain = domain.split(':')[0]
            
        # Get or create site
        # Get organization context from middleware
        org_id = getattr(request, 'org_id', None)
        
        # Simple get or create by domain
        if org_id:
            site = Site.objects.filter(domain=domain, org_id=org_id).first()
        else:
            site = Site.objects.filter(domain=domain).first()
        
        if not site:
            # Create rudimentary site if missing
            site = Site.objects.create(
                domain=domain,
                status='active',
                org_id=org_id
            )
            
    except Exception as e:
        if "duplicate key" in str(e):
            logger.warning(f"Domain collision for {domain}: {e}")
            return Response(
                {'error': 'Domain already registered by another organization'},
                status=status.HTTP_409_CONFLICT
            )
        logger.error(f"Error resolving site for URL {url}: {e}")
        # Fallback to provided site_id if available, though likely to fail if URL parsing failed
        if data.get('site_id'):
            try:
                site = Site.objects.get(id=data['site_id'])
            except Site.DoesNotExist:
                    return Response({'error': 'Site lookup failed'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': 'Could not resolve site from URL'}, status=status.HTTP_400_BAD_REQUEST)

    # Use IndexingService to create job AND trigger worker
    indexing_service = IndexingService()
    
    # Prepare params for service (using validated data + overrides)
    job = indexing_service.create_indexing_job(
        site=site,
        params=data,
        user_id=getattr(request.user, 'id', None), # Might be None for AllowAny
        callback_url=data.get('callback_url')
    )
    

    # Check if this was an idempotent return
    message = 'Indexing task started successfully'
    if job.created_at < timezone.now() - timedelta(seconds=5):
            # Heuristic: if job was created > 5s ago, it's likely an existing job
            message = 'Existing task returned (idempotent)'
    
    return Response({
        'task_id': job.task_id or job.external_job_id,
        'status': job.status,
        'message': message,
        'url': job.url,
        'created_at': job.created_at.isoformat()
    })


# Bug #26 fix: IndexedPage API endpoints for per-URL visibility

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def site_indexed_pages(request, site_id):
    """
    GET /sites/{site_id}/indexed-pages — List indexed pages for a site

    Query parameters:
    - status: Filter by status (indexed, failed, skipped, discovered, queued, processing)
    - content_type: Filter by content type (html, pdf, other)
    - limit: Max results (default 100, max 500)
    - offset: Pagination offset
    - search: Search in URL and title
    """
    # Validate site access using user's organization memberships
    try:
        site = check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Build queryset
    queryset = IndexedPage.objects.filter(site_id=site_id).order_by('-processed_at', '-created_at')

    # Apply filters
    status_filter = request.GET.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    content_type_filter = request.GET.get('content_type')
    if content_type_filter:
        queryset = queryset.filter(content_type=content_type_filter)

    # Apply search
    search_query = request.GET.get('search')
    if search_query:
        queryset = queryset.filter(
            Q(url__icontains=search_query) |
            Q(title__icontains=search_query)
        )

    # Pagination
    try:
        limit = min(int(request.GET.get('limit', 100)), 500)
        offset = int(request.GET.get('offset', 0))
    except (ValueError, TypeError):
        limit = 100
        offset = 0

    total_count = queryset.count()
    pages = queryset[offset:offset + limit]

    serializer = IndexedPageListSerializer(pages, many=True)

    # Calculate summary stats
    stats = {
        'total': total_count,
        'indexed': queryset.filter(status='indexed').count(),
        'failed': queryset.filter(status='failed').count(),
        'skipped': queryset.filter(status='skipped').count(),
    }

    return Response({
        'results': serializer.data,
        'count': total_count,
        'limit': limit,
        'offset': offset,
        'stats': stats
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def indexed_page_detail(request, page_id):
    """
    GET /indexed-pages/{page_id} — Get details of a specific indexed page
    """
    page = get_object_or_404(IndexedPage, id=page_id)

    # Check organization access
    if hasattr(request, 'org_id') and str(page.org_id) != str(request.org_id):
        return Response(
            {'error': 'Page not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = IndexedPageSerializer(page)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([IndexingThrottle])
def add_indexed_page(request, site_id):
    """
    POST /sites/{site_id}/indexed-pages — Manually add a URL to be indexed
    Triggers an immediate indexing job for the single URL.
    """
    from django.db import transaction

    # Validate site access using user's organization memberships
    try:
        site = check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = IndexedPageCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    url = serializer.validated_data['url']

    url = serializer.validated_data['url']
    
    # Use atomic transaction to ensure Page and Job are created together
    with transaction.atomic():
        # Trigger immediate indexing job
        indexing_service = IndexingService()
        
        # Create job first to get the ID
        job = indexing_service.create_indexing_job(
            site=site,
            params={
                'url': url,
                'max_pages': 1,  # Index only this page
            },
            user_id=request.user.id,
            append_mode=True  # CRITICAL: Append to existing index, don't create new namespace
        )
        
        # Create or update the indexed page, linking it to the new job
        page, created = IndexedPage.get_or_create_from_url(
            site_id=site.id,
            indexing_job_id=job.id,
            url=url,
            org_id=site.org_id,
            user_added=True,
            status='queued'  # Mark as queued since job is started
        )
        
        if not created:
            # Ensure existing page is marked as user_added and queued
            page.user_added = True
            page.status = 'queued'
            page.indexing_job_id = job.id
            page.save(update_fields=['user_added', 'status', 'indexing_job_id', 'updated_at'])
            
    return Response(
        IndexedPageSerializer(page).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )

    return Response(
        IndexedPageSerializer(page).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([IndexingThrottle])
def delete_indexed_page(request, page_id):
    """
    DELETE /indexed-pages/{page_id} — Remove an indexed page

    P1.3: Now also removes vectors from Pinecone before deleting the tracking record.
    """
    page = get_object_or_404(IndexedPage, id=page_id)

    # Check organization access
    if hasattr(request, 'org_id') and str(page.org_id) != str(request.org_id):
        return Response(
            {'error': 'Page not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    page_url = page.url
    site_id = page.site_id
    
    # P1.3: Cleanup Pinecone vectors before deleting the record
    deleted_vectors = 0
    try:
        site = Site.objects.get(id=site_id)
        indexing_service = IndexingService()
        deleted_vectors = indexing_service.delete_indexed_page_vectors(site, page_url)
        logger.info(f"Deleted {deleted_vectors} vectors for page {page_url}")
    except Site.DoesNotExist:
        logger.warning(f"Site {site_id} not found, skipping vector cleanup")
    except Exception as e:
        logger.error(f"Failed to cleanup vectors for page {page_id}: {e}")
        # Continue with page deletion even if vector cleanup fails
    
    page.delete()

    return Response({
        'message': f'Indexed page removed: {page_url}',
        'vectors_deleted': deleted_vectors
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([IndexingThrottle])
def bulk_delete_indexed_pages(request, site_id):
    """
    P3.1: POST /sites/{site_id}/indexed-pages/bulk-delete — Delete multiple indexed pages
    
    Request body:
    - page_ids: List of page IDs to delete (max 100)
    """
    # Validate site access using user's organization memberships
    try:
        site = check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    page_ids = request.data.get('page_ids', [])
    
    if not page_ids:
        return Response(
            {'error': 'No page IDs provided'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if len(page_ids) > 100:
        return Response(
            {'error': 'Maximum 100 pages can be deleted at once'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get pages that belong to this site
    pages = IndexedPage.objects.filter(id__in=page_ids, site_id=site_id)
    
    if not pages.exists():
        return Response(
            {'error': 'No matching pages found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Collect URLs for Pinecone cleanup
    urls_to_delete = list(pages.values_list('url', flat=True))
    
    # Cleanup vectors from Pinecone
    deleted_vectors = 0
    try:
        indexing_service = IndexingService()
        for url in urls_to_delete:
            deleted_vectors += indexing_service.delete_indexed_page_vectors(site, url)
        logger.info(f"Bulk delete: {deleted_vectors} vectors deleted for {len(urls_to_delete)} pages")
    except Exception as e:
        logger.error(f"Bulk delete vector cleanup failed: {e}")
    
    # Delete the page records
    deleted_count = pages.count()
    pages.delete()

    return Response({
        'message': f'Successfully deleted {deleted_count} indexed pages',
        'deleted_count': deleted_count,
        'vectors_deleted': deleted_vectors,
        'urls_deleted': urls_to_delete
    })
