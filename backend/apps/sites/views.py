from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django.shortcuts import get_object_or_404
from django.db.models import Q
import logging

from .models import Site, ExcludedURLPattern
from .serializers import (
    SiteSerializer,
    SiteCreateSerializer,
    # SiteVerificationSerializer,  # MVP: Comment out verification serializer
    SiteUpdateSerializer,
    ExcludedURLPatternSerializer,
    ExcludedURLPatternListSerializer,
    ExcludedURLPatternCreateSerializer,
    ExcludedURLPatternUpdateSerializer,
    ExcludedURLPatternBulkCreateSerializer
)
# MVP: Comment out verification service import
# from .services import SiteVerificationService
from apps.core.views import BaseViewSet
from apps.core.exceptions import SiteNotVerified
from apps.usage.services import QuotaService, QuotaLimitExceeded

logger = logging.getLogger(__name__)


class SitesThrottle(UserRateThrottle):
    scope = 'sites'


class SiteViewSet(BaseViewSet):
    """Site management"""
    queryset = Site.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return SiteCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return SiteUpdateSerializer
        return SiteSerializer

    def get_queryset(self):
        """
        Get all sites the user has access to.
        Overriding BaseViewSet to properly handle multi-org users.
        """
        if getattr(self, 'swagger_fake_view', False):
            return Site.objects.none()
            
        request = self.request
        if not request.user.is_authenticated:
            return Site.objects.none()
            
        from apps.core.organization_permissions import get_user_organizations
        user_orgs = get_user_organizations(request.user)
        
        # Filter sites belonging to any of the user's organizations
        return Site.objects.filter(org_id__in=user_orgs.values('id'))

    def create(self, request, *args, **kwargs):
        """Create new site with auto-organization provisioning"""
        # Determine organization
        org_id = getattr(request, 'org_id', None)
        
        from apps.core.organization_permissions import get_user_organizations
        from apps.organizations.models import Organization, Membership
        
        # 1. Try to find existing orgs
        user_orgs = get_user_organizations(request.user)
        
        if not org_id:
            if user_orgs.exists():
                # Default to first organization if not specified
                org_id = str(user_orgs.first().id)
            else:
                # 2. Auto-create "Personal Organization" if none exist
                user_email = request.user.email or request.user.username
                org_name = f"{user_email.split('@')[0]}'s Workspace"
                
                # Create slug from name
                import slugify
                base_slug = slugify.slugify(org_name)
                slug = base_slug
                counter = 1
                while Organization.objects.filter(slug=slug).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                
                org = Organization.objects.create(
                    name=org_name,
                    slug=slug,
                    status='active',
                    plan_tier='basic'
                )
                
                # Add user as owner
                Membership.objects.create(
                    user=request.user,
                    organization=org,
                    role='owner'
                )
                
                org_id = str(org.id)
                logger.info(f"Auto-created personal organization {org.id} for user {request.user.id}")
        
        # Check site limit before creating
        if org_id:
            try:
                QuotaService.enforce_site_limit(org_id)
            except QuotaLimitExceeded as e:
                return Response(
                    {'error': e.message, 'limit_type': e.limit_type},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Save with org_id
        site = serializer.save(org_id=org_id)
        
        return Response(
            SiteSerializer(site).data,
            status=status.HTTP_201_CREATED
        )


    def retrieve(self, request, *args, **kwargs):
        """Get site details"""
        site = self.get_object()
        serializer = self.get_serializer(site)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """Update site settings"""
        site = self.get_object()
        serializer = self.get_serializer(site, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        site = serializer.save()
        
        return Response(SiteSerializer(site).data)


# MVP: Comment out verification endpoint
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def verify_site(request, site_id):
#     """Verify site ownership"""
#     site = get_object_or_404(Site, id=site_id)
#     
#     # MVP: Skip organization access check for easier testing
#     # TODO: Re-enable organization validation for production
#     # if hasattr(request, 'org_id') and str(site.org_id) != str(request.org_id):
#     #     return Response(
#     #         {'error': 'Site not found'}, 
#     #         status=status.HTTP_404_NOT_FOUND
#     #     )
#     
#     serializer = SiteVerificationSerializer(data=request.data, context={'site': site})
#     serializer.is_valid(raise_exception=True)
#     
#     # Perform actual verification
#     verification_service = SiteVerificationService()
#     
#     try:
#         is_verified = verification_service.verify_site(site)
#         
#         if is_verified:
#             verification_service.mark_site_verified(site)
#             return Response({
#                 'message': 'Site verified successfully',
#                 'site': SiteSerializer(site).data
#             })
#         else:
#             verification_service.mark_site_failed(site, 'Verification failed')
#             return Response({
#                 'error': 'Site verification failed. Please check your verification method and try again.'
#             }, status=status.HTTP_400_BAD_REQUEST)
#             
#     except Exception as e:
#         return Response({
#             'error': f'Verification error: {str(e)}'
#         }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# MVP: Comment out verification instructions endpoint
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def site_verification_instructions(request, site_id):
#     """Get site verification instructions"""
#     site = get_object_or_404(Site, id=site_id)
#     
#     # MVP: Skip organization access check for easier testing
#     # TODO: Re-enable organization validation for production
#     # if hasattr(request, 'org_id') and str(site.org_id) != str(request.org_id):
#     #     return Response(
#     #         {'error': 'Site not found'}, 
#     #         status=status.HTTP_404_NOT_FOUND
#     #     )
#     
#     instructions = {
#         'dns': {
#             'type': 'TXT',
#             'name': '_lawa-verification',
#             'value': site.verification_token,
#             'description': 'Add a TXT record to your DNS with the above name and value'
#         },
#         'file': {
#             'filename': f'lawa-verification-{site.verification_token}.txt',
#             'content': site.verification_token,
#             'description': 'Create a file in your website root with the above filename and content'
#         }
#     }
#     
#     return Response({
#         'method': site.verification_method,
#         'token': site.verification_token,
#         'instructions': instructions[site.verification_method]
#     })


# Excluded URL Pattern Management API

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def site_excluded_patterns(request, site_id):
    """
    GET /sites/{site_id}/excluded-patterns/ — List excluded URL patterns for a site

    Query parameters:
    - is_active: Filter by active status (true/false)
    - pattern_type: Filter by pattern type
    - search: Search in pattern and description
    """
    site = get_object_or_404(Site, id=site_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Build queryset
    queryset = ExcludedURLPattern.objects.filter(site_id=site_id).order_by('-created_at')

    # Apply filters
    is_active = request.GET.get('is_active')
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active.lower() == 'true')

    pattern_type = request.GET.get('pattern_type')
    if pattern_type:
        queryset = queryset.filter(pattern_type=pattern_type)

    search = request.GET.get('search')
    if search:
        queryset = queryset.filter(
            Q(pattern__icontains=search) |
            Q(description__icontains=search)
        )

    # Pagination
    try:
        limit = min(int(request.GET.get('limit', 100)), 500)
        offset = int(request.GET.get('offset', 0))
    except (ValueError, TypeError):
        limit = 100
        offset = 0

    total_count = queryset.count()
    patterns = queryset[offset:offset + limit]

    serializer = ExcludedURLPatternListSerializer(patterns, many=True)

    # Calculate stats
    stats = {
        'total': total_count,
        'active': queryset.filter(is_active=True).count(),
        'inactive': queryset.filter(is_active=False).count(),
        'by_type': {}
    }
    for pattern_type_choice in ExcludedURLPattern.PATTERN_TYPE_CHOICES:
        type_code = pattern_type_choice[0]
        stats['by_type'][type_code] = queryset.filter(pattern_type=type_code).count()

    return Response({
        'results': serializer.data,
        'count': total_count,
        'limit': limit,
        'offset': offset,
        'stats': stats,
        'pattern_types': [
            {'value': choice[0], 'label': choice[1]}
            for choice in ExcludedURLPattern.PATTERN_TYPE_CHOICES
        ]
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def add_excluded_pattern(request, site_id):
    """
    POST /sites/{site_id}/excluded-patterns/ — Add a new excluded URL pattern

    Request body:
    - pattern: URL pattern to exclude
    - pattern_type: How to match (exact, prefix, suffix, contains, regex)
    - description: Optional description
    - is_active: Whether pattern is active (default true)
    """
    site = get_object_or_404(Site, id=site_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ExcludedURLPatternCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data

    # Check for duplicate pattern
    existing = ExcludedURLPattern.objects.filter(
        site_id=site_id,
        pattern=data['pattern'],
        pattern_type=data['pattern_type']
    ).first()

    if existing:
        return Response(
            {'error': 'This pattern already exists for this site'},
            status=status.HTTP_409_CONFLICT
        )

    # Create the pattern
    pattern = ExcludedURLPattern.objects.create(
        site_id=site.id,
        org_id=site.org_id,
        pattern=data['pattern'],
        pattern_type=data['pattern_type'],
        description=data.get('description', ''),
        is_active=data.get('is_active', True)
    )

    # P1.2: Trigger Pinecone cleanup for matching URLs after transaction commits
    if pattern.is_active:
        from django.db import transaction
        from apps.indexing.services import IndexingService
        
        def cleanup_vectors():
            try:
                indexing_service = IndexingService()
                result = indexing_service.cleanup_excluded_vectors(site, pattern)
                logger.info(f"Cleanup result for pattern {pattern.id}: {result}")
            except Exception as e:
                logger.error(f"Failed to cleanup vectors for pattern {pattern.id}: {e}")
        
        transaction.on_commit(cleanup_vectors)

    return Response(
        ExcludedURLPatternSerializer(pattern).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def bulk_add_excluded_patterns(request, site_id):
    """
    POST /sites/{site_id}/excluded-patterns/bulk/ — Add multiple excluded URL patterns

    Request body:
    - patterns: List of pattern objects
    """
    site = get_object_or_404(Site, id=site_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ExcludedURLPatternBulkCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    patterns_data = serializer.validated_data['patterns']
    created = []
    skipped = []

    for pattern_data in patterns_data:
        # Check for duplicate
        existing = ExcludedURLPattern.objects.filter(
            site_id=site_id,
            pattern=pattern_data['pattern'],
            pattern_type=pattern_data['pattern_type']
        ).first()

        if existing:
            skipped.append({
                'pattern': pattern_data['pattern'],
                'reason': 'Already exists'
            })
            continue

        # Create the pattern
        pattern = ExcludedURLPattern.objects.create(
            site_id=site.id,
            org_id=site.org_id,
            pattern=pattern_data['pattern'],
            pattern_type=pattern_data['pattern_type'],
            description=pattern_data.get('description', ''),
            is_active=pattern_data.get('is_active', True)
        )
        created.append(ExcludedURLPatternListSerializer(pattern).data)

    return Response({
        'created': created,
        'skipped': skipped,
        'created_count': len(created),
        'skipped_count': len(skipped)
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def excluded_pattern_detail(request, pattern_id):
    """
    GET/PUT/DELETE /excluded-patterns/{pattern_id}/ — Manage a specific excluded pattern
    """
    pattern = get_object_or_404(ExcludedURLPattern, id=pattern_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_organization_access, OrganizationAccessError, ResourceNotInOrganizationError
    try:
        if pattern.org_id:
            check_organization_access(request.user, pattern.org_id)
    except (OrganizationAccessError, ResourceNotInOrganizationError) as e:
        return Response(
            {'error': 'Pattern not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = ExcludedURLPatternSerializer(pattern)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ExcludedURLPatternUpdateSerializer(pattern, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Check for duplicate if pattern/type changed
        if 'pattern' in serializer.validated_data or 'pattern_type' in serializer.validated_data:
            new_pattern = serializer.validated_data.get('pattern', pattern.pattern)
            new_type = serializer.validated_data.get('pattern_type', pattern.pattern_type)

            existing = ExcludedURLPattern.objects.filter(
                site_id=pattern.site_id,
                pattern=new_pattern,
                pattern_type=new_type
            ).exclude(id=pattern.id).first()

            if existing:
                return Response(
                    {'error': 'This pattern already exists for this site'},
                    status=status.HTTP_409_CONFLICT
                )

        serializer.save()
        return Response(ExcludedURLPatternSerializer(pattern).data)

    elif request.method == 'DELETE':
        pattern_info = {'pattern': pattern.pattern, 'id': str(pattern.id)}
        pattern.delete()
        return Response({
            'message': 'Pattern deleted successfully',
            'deleted': pattern_info
        })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def toggle_excluded_pattern(request, pattern_id):
    """
    POST /excluded-patterns/{pattern_id}/toggle/ — Toggle pattern active status
    """
    pattern = get_object_or_404(ExcludedURLPattern, id=pattern_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_organization_access, OrganizationAccessError, ResourceNotInOrganizationError
    try:
        if pattern.org_id:
            check_organization_access(request.user, pattern.org_id)
    except (OrganizationAccessError, ResourceNotInOrganizationError) as e:
        return Response(
            {'error': 'Pattern not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    pattern.is_active = not pattern.is_active
    pattern.save(update_fields=['is_active', 'updated_at'])

    return Response({
        'message': f'Pattern {"activated" if pattern.is_active else "deactivated"}',
        'pattern': ExcludedURLPatternSerializer(pattern).data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def test_excluded_pattern(request, pattern_id):
    """
    POST /excluded-patterns/{pattern_id}/test/ — Test a pattern against URLs

    Request body:
    - urls: List of URLs to test against the pattern
    """
    pattern = get_object_or_404(ExcludedURLPattern, id=pattern_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_organization_access, OrganizationAccessError, ResourceNotInOrganizationError
    try:
        if pattern.org_id:
            check_organization_access(request.user, pattern.org_id)
    except (OrganizationAccessError, ResourceNotInOrganizationError) as e:
        return Response(
            {'error': 'Pattern not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    urls = request.data.get('urls', [])
    if not urls:
        return Response(
            {'error': 'No URLs provided to test'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if len(urls) > 100:
        return Response(
            {'error': 'Maximum 100 URLs can be tested at once'},
            status=status.HTTP_400_BAD_REQUEST
        )

    results = []
    for url in urls:
        matches = pattern.matches_url(url)
        results.append({
            'url': url,
            'matches': matches
        })

    matched_count = sum(1 for r in results if r['matches'])

    return Response({
        'pattern': ExcludedURLPatternListSerializer(pattern).data,
        'results': results,
        'summary': {
            'total': len(results),
            'matched': matched_count,
            'not_matched': len(results) - matched_count
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def apply_exclusions_now(request, site_id):
    """
    P3.2: POST /sites/{site_id}/excluded-patterns/apply-now — Apply all exclusions immediately
    
    Removes vectors from Pinecone for all URLs matching active exclusion patterns
    without requiring a full re-index.
    """
    site = get_object_or_404(Site, id=site_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Get all active patterns for this site
    patterns = ExcludedURLPattern.objects.filter(site_id=site_id, is_active=True)
    
    if not patterns.exists():
        return Response({
            'message': 'No active exclusion patterns found',
            'patterns_applied': 0,
            'urls_affected': 0,
            'vectors_deleted': 0
        })

    # Apply each pattern
    from apps.indexing.services import IndexingService
    from apps.indexing.models import IndexedPage
    
    indexing_service = IndexingService()
    total_urls_affected = 0
    total_vectors_deleted = 0
    patterns_applied = []

    for pattern in patterns:
        try:
            result = indexing_service.cleanup_excluded_vectors(site, pattern)
            total_urls_affected += len(result.get('matched_urls', []))
            total_vectors_deleted += result.get('deleted_count', 0)
            patterns_applied.append({
                'pattern': pattern.pattern,
                'pattern_type': pattern.pattern_type,
                'urls_matched': len(result.get('matched_urls', []))
            })
            logger.info(f"Applied exclusion pattern {pattern.pattern}: {result}")
        except Exception as e:
            logger.error(f"Failed to apply exclusion pattern {pattern.id}: {e}")
            patterns_applied.append({
                'pattern': pattern.pattern,
                'pattern_type': pattern.pattern_type,
                'error': 'An internal error occurred while processing this pattern.'
            })

    return Response({
        'message': f'Applied {len(patterns)} exclusion patterns',
        'patterns_applied': patterns_applied,
        'urls_affected': total_urls_affected,
        'vectors_deleted': total_vectors_deleted
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def preview_exclusion_impact(request, site_id):
    """
    P3.3: POST /sites/{site_id}/excluded-patterns/preview — Preview impact of exclusion patterns
    
    Shows which indexed pages would be affected by active exclusion patterns
    without actually deleting anything.
    
    Request body (optional):
    - pattern: Test a specific pattern without saving it
    - pattern_type: Type of the test pattern
    """
    site = get_object_or_404(Site, id=site_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    from apps.indexing.models import IndexedPage
    
    # Get all indexed pages for this site
    indexed_pages = IndexedPage.objects.filter(
        site_id=site_id,
        status='indexed'
    ).values_list('url', flat=True)
    
    indexed_urls = list(indexed_pages)
    
    if not indexed_urls:
        return Response({
            'message': 'No indexed pages found',
            'indexed_pages_count': 0,
            'would_be_excluded': 0,
            'patterns': []
        })

    # Check for test pattern in request
    test_pattern = request.data.get('pattern')
    test_pattern_type = request.data.get('pattern_type', 'prefix')
    
    patterns_to_check = []
    
    if test_pattern:
        # Create a temporary pattern object for testing
        temp_pattern = ExcludedURLPattern(
            pattern=test_pattern,
            pattern_type=test_pattern_type,
            is_active=True
        )
        patterns_to_check.append({
            'pattern': temp_pattern,
            'is_saved': False
        })
    
    # Also check saved patterns
    saved_patterns = ExcludedURLPattern.objects.filter(site_id=site_id, is_active=True)
    for p in saved_patterns:
        patterns_to_check.append({
            'pattern': p,
            'is_saved': True
        })
    
    # Calculate impact
    all_affected_urls = set()
    pattern_results = []
    
    for item in patterns_to_check:
        pattern = item['pattern']
        matched_urls = [url for url in indexed_urls if pattern.matches_url(url)]
        all_affected_urls.update(matched_urls)
        
        pattern_results.append({
            'pattern': pattern.pattern,
            'pattern_type': pattern.pattern_type,
            'is_saved': item['is_saved'],
            'urls_matched': len(matched_urls),
            'sample_urls': matched_urls[:10]  # First 10 as sample
        })

    return Response({
        'message': 'Preview generated',
        'indexed_pages_count': len(indexed_urls),
        'impact_count': len(all_affected_urls),
        'safe_count': len(indexed_urls) - len(all_affected_urls),
        'affected_samples': list(all_affected_urls)[:20],  # First 20 as sample
        # Also keep old names for backward compatibility
        'would_be_excluded': len(all_affected_urls),
        'remaining_after_exclusion': len(indexed_urls) - len(all_affected_urls),
        'patterns': pattern_results
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def get_exclusion_templates(request):
    """
    P4.2: GET /excluded-patterns/templates — Get common exclusion pattern templates
    
    Returns a list of commonly used exclusion patterns for quick addition.
    """
    templates = [
        {
            'name': 'Admin Pages',
            'description': 'Exclude admin and backend pages',
            'patterns': [
                {'pattern': '/admin', 'pattern_type': 'prefix', 'description': 'Django admin'},
                {'pattern': '/wp-admin', 'pattern_type': 'prefix', 'description': 'WordPress admin'},
                {'pattern': '/administrator', 'pattern_type': 'prefix', 'description': 'Generic admin'},
            ]
        },
        {
            'name': 'API Endpoints',
            'description': 'Exclude API endpoints',
            'patterns': [
                {'pattern': '/api', 'pattern_type': 'prefix', 'description': 'API routes'},
                {'pattern': '/v1', 'pattern_type': 'prefix', 'description': 'API version 1'},
                {'pattern': '/graphql', 'pattern_type': 'prefix', 'description': 'GraphQL endpoint'},
            ]
        },
        {
            'name': 'Authentication',
            'description': 'Exclude login and auth pages',
            'patterns': [
                {'pattern': '/login', 'pattern_type': 'contains', 'description': 'Login pages'},
                {'pattern': '/signin', 'pattern_type': 'contains', 'description': 'Sign-in pages'},
                {'pattern': '/signup', 'pattern_type': 'contains', 'description': 'Sign-up pages'},
                {'pattern': '/register', 'pattern_type': 'contains', 'description': 'Registration pages'},
                {'pattern': '/auth', 'pattern_type': 'prefix', 'description': 'Auth routes'},
            ]
        },
        {
            'name': 'User Dashboards',
            'description': 'Exclude user-specific dashboard pages',
            'patterns': [
                {'pattern': '/dashboard', 'pattern_type': 'prefix', 'description': 'User dashboards'},
                {'pattern': '/account', 'pattern_type': 'prefix', 'description': 'Account pages'},
                {'pattern': '/profile', 'pattern_type': 'prefix', 'description': 'User profiles'},
                {'pattern': '/settings', 'pattern_type': 'prefix', 'description': 'Settings pages'},
            ]
        },
        {
            'name': 'File Types',
            'description': 'Exclude specific file types',
            'patterns': [
                {'pattern': '.pdf', 'pattern_type': 'suffix', 'description': 'PDF files'},
                {'pattern': '.zip', 'pattern_type': 'suffix', 'description': 'ZIP archives'},
                {'pattern': '.exe', 'pattern_type': 'suffix', 'description': 'Executable files'},
                {'pattern': '.dmg', 'pattern_type': 'suffix', 'description': 'macOS installers'},
            ]
        },
        {
            'name': 'Development',
            'description': 'Exclude development and testing URLs',
            'patterns': [
                {'pattern': 'localhost', 'pattern_type': 'contains', 'description': 'Local development'},
                {'pattern': '127.0.0.1', 'pattern_type': 'contains', 'description': 'Local IP'},
                {'pattern': '.local', 'pattern_type': 'suffix', 'description': 'Local domains'},
                {'pattern': '/test', 'pattern_type': 'prefix', 'description': 'Test pages'},
                {'pattern': 'staging', 'pattern_type': 'contains', 'description': 'Staging environments'},
            ]
        },
        {
            'name': 'E-commerce',
            'description': 'Exclude cart and checkout pages',
            'patterns': [
                {'pattern': '/cart', 'pattern_type': 'prefix', 'description': 'Shopping cart'},
                {'pattern': '/checkout', 'pattern_type': 'prefix', 'description': 'Checkout flow'},
                {'pattern': '/payment', 'pattern_type': 'prefix', 'description': 'Payment pages'},
                {'pattern': '/order', 'pattern_type': 'prefix', 'description': 'Order pages'},
            ]
        },
    ]
    
    # Convert to category-keyed format for frontend
    # Frontend expects: { 'Admin Pages': [...], 'API Endpoints': [...], ... }
    templates_by_category = {}
    for template_group in templates:
        templates_by_category[template_group['name']] = template_group['patterns']
    
    return Response(templates_by_category)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def apply_template(request, site_id):
    """
    P4.2: POST /sites/{site_id}/excluded-patterns/apply-template — Apply a template
    
    Request body:
    - template_name: Name of the template to apply
    - patterns: List of patterns from the template to apply (all if not specified)
    """
    site = get_object_or_404(Site, id=site_id)

    # Check organization access
    # Check organization access
    from apps.core.organization_permissions import check_site_access, ResourceNotInOrganizationError
    try:
        check_site_access(request.user, site_id)
    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'Site not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    patterns_data = request.data.get('patterns', [])
    
    if not patterns_data:
        return Response(
            {'error': 'No patterns provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    created = []
    skipped = []

    for pattern_data in patterns_data:
        # Check for duplicate
        existing = ExcludedURLPattern.objects.filter(
            site_id=site_id,
            pattern=pattern_data['pattern'],
            pattern_type=pattern_data['pattern_type']
        ).first()

        if existing:
            skipped.append({
                'pattern': pattern_data['pattern'],
                'reason': 'Already exists'
            })
            continue

        # Create the pattern
        pattern = ExcludedURLPattern.objects.create(
            site_id=site.id,
            org_id=site.org_id,
            pattern=pattern_data['pattern'],
            pattern_type=pattern_data['pattern_type'],
            description=pattern_data.get('description', ''),
            is_active=True
        )
        created.append(ExcludedURLPatternListSerializer(pattern).data)

    # Trigger cleanup for newly created patterns
    if created:
        from django.db import transaction
        from apps.indexing.services import IndexingService
        
        def cleanup_vectors():
            try:
                indexing_service = IndexingService()
                for pattern_data in created:
                    pattern = ExcludedURLPattern.objects.get(id=pattern_data['id'])
                    result = indexing_service.cleanup_excluded_vectors(site, pattern)
                    logger.info(f"Template cleanup for pattern {pattern.pattern}: {result}")
            except Exception as e:
                logger.error(f"Failed to cleanup vectors for template patterns: {e}")
        
        transaction.on_commit(cleanup_vectors)

    return Response({
        'message': f'Applied template patterns',
        'created': created,
        'skipped': skipped,
        'created_count': len(created),
        'skipped_count': len(skipped)
    }, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([SitesThrottle])
def undo_exclusion(request, pattern_id):
    """
    P4.1: POST /excluded-patterns/{pattern_id}/undo — Undo an exclusion
    
    Re-indexes URLs that were excluded by this pattern by triggering a fresh index.
    Uses append mode to add pages to the existing active namespace.
    
    Request body:
    - urls: Optional list of specific URLs to restore (all matching if not specified)
    """
    pattern = get_object_or_404(ExcludedURLPattern, id=pattern_id)
    
    # Check organization access
    if hasattr(request, 'org_id') and str(pattern.org_id) != str(request.org_id):
        return Response(
            {'error': 'Pattern not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    from apps.indexing.models import IndexedPage
    from apps.indexing.services import IndexingService
    
    site = Site.objects.get(id=pattern.site_id)
    
    # Get URLs to restore
    urls_to_restore = request.data.get('urls', [])
    
    if not urls_to_restore:
        # Find pages that MATCH this exclusion pattern
        # Instead of looking at error_message, we check which indexed/skipped pages match the pattern
        all_pages = IndexedPage.objects.filter(
            site_id=pattern.site_id,
            status__in=['skipped', 'excluded']
        ).values_list('url', flat=True)
        
        # Filter by pattern match
        urls_to_restore = [url for url in all_pages if pattern.matches_url(url)]
    
    if not urls_to_restore:
        return Response({
            'message': 'No URLs found that match this exclusion pattern',
            'restored_count': 0,
            'pattern': pattern.pattern
        })

    # Mark pages for re-indexing by changing status
    restored = IndexedPage.objects.filter(
        site_id=pattern.site_id,
        url__in=urls_to_restore,
        status__in=['skipped', 'excluded']
    ).update(
        status='queued',
        error_message=''
    )
    
    # Check if site has an active namespace to append to
    if not site.active_namespace:
        return Response({
            'message': f'Marked {restored} URLs for re-indexing, but no active index exists. Please run a full re-index.',
            'restored_count': restored,
            'jobs_created': 0,
            'note': 'No active namespace - full re-index required'
        })
    
    # Create indexing job(s) to re-index these URLs with append_mode
    indexing_service = IndexingService()
    jobs_created = []
    
    # Create a single job per URL (with append_mode to use existing namespace)
    # Batch into groups to avoid overwhelming the system
    batch_size = 5
    for i in range(0, len(urls_to_restore), batch_size):
        batch = urls_to_restore[i:i + batch_size]
        for url in batch:
            try:
                job = indexing_service.create_indexing_job(
                    site=site,
                    params={'url': url, 'max_pages': 1},
                    user_id=request.user.id,
                    append_mode=True  # Use existing active_namespace
                )
                jobs_created.append(str(job.id))
                logger.info(f"Created append-mode job {job.id} for URL: {url}")
            except Exception as e:
                logger.error(f"Failed to create re-index job for {url}: {e}")

    return Response({
        'message': f'Undo initiated for {restored} URLs',
        'restored_count': restored,
        'jobs_created': len(jobs_created),
        'job_ids': jobs_created[:5],  # First 5 as sample
        'target_namespace': site.active_namespace
    })



