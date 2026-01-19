from rest_framework import viewsets, views, status, filters
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta

from apps.admin_api.permissions import (
    IsAdminUser, IsSuperAdmin, AdminIPAllowlist, AdminWithIPCheck,
    CanImpersonate, CanPerformBulkOperations, CanExportData,
    UserManagerAdmin, SupportAdmin, BillingAdmin
)
from apps.core.rate_limiting import (
    AdminRateThrottle, AdminBurstThrottle, AdminLoginThrottle,
    AdminLoginDailyThrottle, AdminSensitiveOperationThrottle, AdminExportThrottle
)
from apps.admin_api.analytics import AdminStatsService
from apps.usage.tier_config import TIER_FEATURES, get_tier_limits
from apps.admin_api.models import AdminAuditLog, LoginHistory
from apps.admin_api.serializers import (
    UserListSerializer, UserDetailSerializer, UserUpdateSerializer,
    OrganizationListSerializer, OrganizationDetailSerializer,
    AdminActionSerializer, QuotaUpdateSerializer,
    IndexingJobSerializer, ChatbotAdminSerializer, SiteAdminSerializer,
    AdminAuditLogSerializer, LoginHistorySerializer, BulkActionSerializer,
    UpgradeInterestAdminSerializer, UpgradeInterestUpdateSerializer,
    FeedbackListSerializer, FeedbackDetailSerializer, FeedbackUpdateSerializer,
    FAQCategorySerializer, FAQCategoryCreateUpdateSerializer,
    FAQSerializer, FAQCreateUpdateSerializer,
    HelpArticleListSerializer, HelpArticleDetailSerializer, HelpArticleCreateUpdateSerializer,
    AdminLoginSerializer, AdminUserSerializer
)
from apps.auth.models import User
from apps.organizations.models import Organization
from apps.usage.models import Subscription, UpgradeInterest
from apps.usage.services import QuotaService
from apps.indexing.models import IndexingJob
from apps.chatbot.models import Chatbot
from apps.sites.models import Site
from apps.support.models import Feedback, FAQ, FAQCategory, HelpArticle
from apps.support.services import feedback_notification_service

from django.core.mail import send_mail
import logging
import csv
from io import StringIO
from django.http import HttpResponse

logger = logging.getLogger(__name__)


# =====================
# Admin Authentication
# =====================

def get_client_ip(request):
    """Extract client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AdminLoginThrottle, AdminLoginDailyThrottle])
def admin_login(request):
    """
    Admin-only login endpoint with brute force protection.

    POST /v1/admin/auth/login/

    This endpoint validates credentials AND admin status BEFORE issuing tokens.
    Non-admin users will be rejected with 403 Forbidden.

    Rate limits:
        - 5 attempts per minute per IP
        - 20 attempts per day per IP

    Request body:
        - email: Admin email
        - password: Admin password

    Returns:
        - user: Admin user details
        - tokens: JWT access and refresh tokens
        - is_admin: Always true for successful login
    """
    serializer = AdminLoginSerializer(data=request.data)

    # Get client info for audit logging
    client_ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

    if not serializer.is_valid():
        # Log failed login attempt
        email = request.data.get('email', 'unknown')
        logger.warning(
            f"Admin login failed for {email} from {client_ip}",
            extra={'email': email, 'ip': client_ip, 'errors': serializer.errors}
        )

        # Try to find user for login history (even if login failed)
        try:
            user = User.objects.get(email=email)
            LoginHistory.objects.create(
                user=user,
                success=False,
                ip_address=client_ip,
                user_agent=user_agent
            )
        except User.DoesNotExist:
            pass

        # Return generic error message (don't reveal if user exists)
        error_message = 'Invalid credentials or insufficient privileges'
        if 'non_field_errors' in serializer.errors:
            error_message = serializer.errors['non_field_errors'][0]

        return Response(
            {'error': error_message},
            status=status.HTTP_403_FORBIDDEN
        )

    user = serializer.validated_data['user']

    # Check if 2FA is enabled
    from apps.admin_api.models import Admin2FA
    from django.core.cache import cache
    import secrets

    if Admin2FA.is_2fa_enabled(user):
        # 2FA is enabled - return temp token for 2FA verification
        temp_token = secrets.token_urlsafe(32)

        # Store user ID in cache with temp token (expires in 5 minutes)
        cache_key = f'admin_2fa_pending_{temp_token}'
        cache.set(cache_key, {'user_id': str(user.id)}, timeout=300)

        logger.info(
            f"Admin login requires 2FA for {user.email} from {client_ip}",
            extra={'user_id': str(user.id), 'email': user.email, 'ip': client_ip}
        )

        return Response({
            'requires_2fa': True,
            'temp_token': temp_token,
            'message': 'Two-factor authentication required. Please provide your 2FA code.'
        })

    # No 2FA - proceed with normal login
    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token

    # Add admin flag to token
    access_token['is_admin'] = True
    access_token['is_superuser'] = user.is_superuser
    access_token['is_staff'] = user.is_staff

    # Log successful admin login
    logger.info(
        f"Admin login successful for {user.email} from {client_ip}",
        extra={'user_id': str(user.id), 'email': user.email, 'ip': client_ip}
    )

    # Record login history
    LoginHistory.objects.create(
        user=user,
        success=True,
        ip_address=client_ip,
        user_agent=user_agent
    )

    # Create audit log entry
    AdminAuditLog.objects.create(
        admin=user,
        admin_email=user.email,
        action='system.config_change',  # Use existing action type for admin login
        target_type='user',
        target_id=str(user.id),
        target_label=user.email,
        ip_address=client_ip,
        user_agent=user_agent,
        details={'login_method': 'admin_portal', 'action': 'admin_login'}
    )

    # Update last login
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])

    return Response({
        'user': AdminUserSerializer(user).data,
        'tokens': {
            'access': str(access_token),
            'refresh': str(refresh),
        },
        'is_admin': True,
        'requires_2fa': False
    })


class AdminStatsViews(viewsets.ViewSet):
    """Admin statistics endpoints with rate limiting."""
    permission_classes = [IsAdminUser, AdminIPAllowlist]
    throttle_classes = [AdminRateThrottle, AdminBurstThrottle]

    @action(detail=False, methods=['get'])
    def overview(self, request):
        stats = AdminStatsService.get_overview_stats()
        return Response(stats)

    @action(detail=False, methods=['get'])
    def growth(self, request):
        days = int(request.query_params.get('days', 30))
        data = AdminStatsService.get_user_growth_chart(days)
        return Response(data)

    @action(detail=False, methods=['get'])
    def revenue(self, request):
        months = int(request.query_params.get('months', 12))
        data = AdminStatsService.get_revenue_chart(months)
        return Response(data)

    @action(detail=False, methods=['get'])
    def usage(self, request):
        days = int(request.query_params.get('days', 30))
        data = AdminStatsService.get_usage_trends(days)
        return Response(data)

    @action(detail=False, methods=['get'])
    def plans(self, request):
        data = AdminStatsService.get_plan_distribution()
        return Response(data)


class UserViewSet(viewsets.ModelViewSet):
    """
    Admin user management with full CRUD capabilities.
    Supports filtering, searching, and admin actions.

    Rate limits:
        - 100 requests/minute for general operations
        - 30 requests/minute burst protection
    """
    queryset = User.objects.all().order_by('-created_at')
    serializer_class = UserListSerializer
    permission_classes = [IsAdminUser, AdminIPAllowlist]
    throttle_classes = [AdminRateThrottle, AdminBurstThrottle]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'is_active', 'is_staff', 'is_email_verified']
    search_fields = ['email', 'name']
    ordering_fields = ['created_at', 'last_login', 'email', 'name']
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return UserDetailSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserListSerializer
    
    def partial_update(self, request, *args, **kwargs):
        """
        PATCH user fields that admin is allowed to update.
        NOT allowed: email, name (per requirements).
        Allowed: status, is_active, is_email_verified, is_staff.
        """
        instance = self.get_object()
        
        # Filter out disallowed fields
        allowed_fields = {'status', 'is_active', 'is_email_verified', 'is_staff'}
        data = {k: v for k, v in request.data.items() if k in allowed_fields}
        
        if not data:
            return Response(
                {'error': 'No valid fields to update. Allowed: status, is_active, is_email_verified, is_staff'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        logger.info(f"Admin updated user {instance.id}: {data}")
        return Response(UserDetailSerializer(instance).data)

    @action(detail=True, methods=['post'])
    def actions(self, request, pk=None):
        """Perform admin actions on a user"""
        user = self.get_object()
        serializer = AdminActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        action_type = serializer.validated_data['action']
        payload = serializer.validated_data.get('payload', {})
        
        if action_type == 'suspend':
            user.status = 'suspended'
            user.is_active = False
            user.save()
            AdminAuditLog.log(
                admin=request.user, action='user.suspend',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin suspended user {user.id}")
            return Response({'status': 'suspended', 'user': UserDetailSerializer(user).data})
            
        elif action_type == 'activate':
            user.status = 'active'
            user.is_active = True
            user.save()
            AdminAuditLog.log(
                admin=request.user, action='user.activate',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin activated user {user.id}")
            return Response({'status': 'activated', 'user': UserDetailSerializer(user).data})
            
        elif action_type == 'verify_email':
            user.is_email_verified = True
            user.save()
            AdminAuditLog.log(
                admin=request.user, action='user.verify_email',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin verified email for user {user.id}")
            return Response({'status': 'email_verified', 'user': UserDetailSerializer(user).data})
            
        elif action_type == 'unverify_email':
            user.is_email_verified = False
            user.save()
            AdminAuditLog.log(
                admin=request.user, action='user.unverify_email',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin unverified email for user {user.id}")
            return Response({'status': 'email_unverified', 'user': UserDetailSerializer(user).data})
            
        elif action_type == 'delete':
            # Soft delete - deactivate and mark as inactive
            user.status = 'inactive'
            user.is_active = False
            user.save()
            AdminAuditLog.log(
                admin=request.user, action='user.delete',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin soft-deleted user {user.id}")
            return Response({'status': 'deleted', 'message': 'User has been deactivated'})
            
        elif action_type == 'reset_password':
            # Trigger password reset email workflow
            from apps.auth.services import send_password_reset_email
            try:
                send_password_reset_email(user)
            except Exception as e:
                logger.warning(f"Password reset email failed: {e}")
            AdminAuditLog.log(
                admin=request.user, action='user.reset_password',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin triggered password reset for user {user.id}")
            return Response({'status': 'password_reset_email_sent'})
        
        elif action_type == 'resend_verification':
            # Resend OTP verification email
            from apps.auth.services import send_otp_email
            try:
                send_otp_email(user)
            except Exception as e:
                logger.warning(f"Verification email failed: {e}")
            AdminAuditLog.log(
                admin=request.user, action='user.resend_verification',
                target_type='user', target_id=user.id, target_label=user.email,
                request=request
            )
            logger.info(f"Admin resent verification for user {user.id}")
            return Response({'status': 'verification_email_sent'})
            
        elif action_type == 'send_email':
            subject = payload.get('subject')
            body = payload.get('body')
            if not subject or not body:
                return Response({'error': 'Subject and body required'}, status=400)
                
            try:
                send_mail(
                    subject,
                    body,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                logger.info(f"Admin sent email to user {user.id}")
                return Response({'status': 'sent'})
            except Exception as e:
                logger.error(f"Failed to send email: {e}")
                return Response({'error': str(e)}, status=500)
                
        return Response({'status': 'unknown_action'}, status=400)
    
    @action(detail=True, methods=['get'])
    def login_history(self, request, pk=None):
        """Get login history for a user"""
        user = self.get_object()
        history = LoginHistory.objects.filter(user=user).order_by('-created_at')[:50]
        serializer = LoginHistorySerializer(history, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def jobs(self, request, pk=None):
        """Get indexing jobs for a user's organizations"""
        user = self.get_object()
        org_ids = user.memberships.values_list('organization_id', flat=True)
        site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
        
        jobs = IndexingJob.objects.filter(site_id__in=site_ids).order_by('-created_at')
        
        # Pagination
        limit = min(int(request.query_params.get('limit', 50)), 100)
        offset = int(request.query_params.get('offset', 0))
        total = jobs.count()
        jobs = jobs[offset:offset + limit]
        
        serializer = IndexingJobSerializer(jobs, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'limit': limit,
            'offset': offset
        })

    @action(detail=True, methods=['get'])
    def chatbots(self, request, pk=None):
        """Get chatbots for a user's organizations"""
        user = self.get_object()
        org_ids = user.memberships.values_list('organization_id', flat=True)
        site_ids = Site.objects.filter(org_id__in=org_ids).values_list('id', flat=True)
        
        chatbots = Chatbot.objects.filter(site_id__in=site_ids).order_by('-created_at')
        
        serializer = ChatbotAdminSerializer(chatbots, many=True)
        return Response({'results': serializer.data, 'count': chatbots.count()})

    @action(detail=True, methods=['get'])
    def sites(self, request, pk=None):
        """Get sites for a user's organizations"""
        user = self.get_object()
        org_ids = user.memberships.values_list('organization_id', flat=True)
        
        sites = Site.objects.filter(org_id__in=org_ids).order_by('-created_at')
        serializer = SiteAdminSerializer(sites, many=True)
        return Response({'results': serializer.data, 'count': sites.count()})


class OrganizationViewSet(viewsets.ModelViewSet):
    """
    Admin organization management with quota control.

    Rate limits:
        - 100 requests/minute for general operations
        - 30 requests/minute burst protection
    """
    queryset = Organization.objects.all().order_by('-created_at')
    serializer_class = OrganizationListSerializer
    permission_classes = [IsAdminUser, AdminIPAllowlist]
    throttle_classes = [AdminRateThrottle, AdminBurstThrottle]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'plan_tier']
    search_fields = ['name', 'slug']
    ordering_fields = ['created_at', 'name']
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return OrganizationDetailSerializer
        return OrganizationListSerializer

    @action(detail=True, methods=['get', 'patch'])
    def quotas(self, request, pk=None):
        """
        GET: Get current limits and usage.
        PATCH: Update limits (requires confirmation).
        """
        org = self.get_object()
        
        if request.method == 'GET':
            limits = QuotaService.get_org_limits(org.id)
            usage = QuotaService.get_org_usage(org.id)
            return Response({
                'limits': limits,
                'usage': usage,
                'plan_tier': org.plan_tier
            })
        
        elif request.method == 'PATCH':
            serializer = QuotaUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            new_limits = serializer.validated_data['limits']
            
            # Update using QuotaService
            quota = QuotaService.update_org_limits(org.id, new_limits)
            
            logger.info(f"Admin updated quotas for org {org.id}: {new_limits}")
            
            return Response({
                'status': 'limits_updated',
                'limits': QuotaService.get_org_limits(org.id),
                'usage': QuotaService.get_org_usage(org.id),
                'message': 'Limits have been updated and will take effect immediately.'
            })

    @action(detail=True, methods=['get'])
    def jobs(self, request, pk=None):
        """Get all indexing jobs for this organization"""
        org = self.get_object()
        site_ids = Site.objects.filter(org_id=org.id).values_list('id', flat=True)
        
        jobs = IndexingJob.objects.filter(site_id__in=site_ids).order_by('-created_at')
        serializer = IndexingJobSerializer(jobs, many=True)
        return Response({'results': serializer.data, 'count': jobs.count()})

    @action(detail=True, methods=['get'])
    def chatbots(self, request, pk=None):
        """Get all chatbots for this organization"""
        org = self.get_object()
        site_ids = Site.objects.filter(org_id=org.id).values_list('id', flat=True)
        
        chatbots = Chatbot.objects.filter(site_id__in=site_ids).order_by('-created_at')
        serializer = ChatbotAdminSerializer(chatbots, many=True)
        return Response({'results': serializer.data, 'count': chatbots.count()})

    @action(detail=True, methods=['get'])
    def sites(self, request, pk=None):
        """Get all sites for this organization"""
        org = self.get_object()
        sites = Site.objects.filter(org_id=org.id).order_by('-created_at')
        serializer = SiteAdminSerializer(sites, many=True)
        return Response({'results': serializer.data, 'count': sites.count()})


# Global list views for all jobs and chatbots
@api_view(['GET'])
@permission_classes([IsAdminUser])
def all_jobs(request):
    """List all indexing jobs across the platform"""
    jobs = IndexingJob.objects.all().order_by('-created_at')

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        jobs = jobs.filter(status=status_filter)

    site_id = request.query_params.get('site_id')
    if site_id:
        jobs = jobs.filter(site_id=site_id)

    org_id = request.query_params.get('org_id')
    if org_id:
        jobs = jobs.filter(org_id=org_id)

    # Search by domain (join with Site)
    search = request.query_params.get('search')
    if search:
        site_ids = Site.objects.filter(domain__icontains=search).values_list('id', flat=True)
        jobs = jobs.filter(Q(site_id__in=site_ids) | Q(url__icontains=search))

    # Get stats before pagination
    stats = {
        'total': jobs.count(),
        'running': jobs.filter(status__in=['running', 'processing', 'collecting_urls', 'processing_urls']).count(),
        'completed': jobs.filter(status='completed').count(),
        'failed': jobs.filter(status='failed').count(),
        'pending': jobs.filter(status__in=['queued', 'pending']).count(),
    }

    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = jobs.count()
    jobs = jobs[offset:offset + limit]

    serializer = IndexingJobSerializer(jobs, many=True)
    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset,
        'stats': stats
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def job_detail(request, job_id):
    """Get detailed job information"""
    try:
        job = IndexingJob.objects.get(id=job_id)
    except IndexingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = IndexingJobSerializer(job)
    data = serializer.data

    # Add additional details
    try:
        site = Site.objects.get(id=job.site_id)
        data['site_name'] = site.name
        data['site_status'] = site.status
    except Site.DoesNotExist:
        pass

    if job.org_id:
        try:
            org = Organization.objects.get(id=job.org_id)
            data['organization'] = {
                'id': str(org.id),
                'name': org.name,
                'tier': org.plan_tier
            }
        except Organization.DoesNotExist:
            pass

    return Response(data)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def job_action(request, job_id):
    """Perform action on a job (cancel, retry)"""
    try:
        job = IndexingJob.objects.get(id=job_id)
    except IndexingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)

    action = request.data.get('action')

    if action == 'cancel':
        if job.status in ['running', 'processing', 'collecting_urls', 'processing_urls', 'queued', 'pending']:
            job.mark_cancelled()
            AdminAuditLog.log(
                admin=request.user,
                action='job.cancel',
                target_type='indexing_job',
                target_id=str(job.id),
                target_label=f"Job for {job.url}",
                request=request
            )
            logger.info(f"Admin cancelled job {job.id}")
            return Response({'status': 'cancelled', 'job': IndexingJobSerializer(job).data})
        else:
            return Response({'error': f'Cannot cancel job with status {job.status}'}, status=400)

    elif action == 'retry':
        if job.status in ['failed', 'cancelled']:
            # Create a new job with same parameters
            from apps.indexing.services import IndexingService
            try:
                site = Site.objects.get(id=job.site_id)
                service = IndexingService()
                new_job = service.create_indexing_job(site, {
                    'url': job.url,
                    'max_pages': job.max_pages,
                })
                AdminAuditLog.log(
                    admin=request.user,
                    action='job.retry',
                    target_type='indexing_job',
                    target_id=str(job.id),
                    target_label=f"Job for {job.url}",
                    details={'new_job_id': str(new_job.id) if new_job else None},
                    request=request
                )
                logger.info(f"Admin retried job {job.id}, new job: {new_job.id if new_job else 'failed'}")
                return Response({
                    'status': 'retried',
                    'old_job_id': str(job.id),
                    'new_job': IndexingJobSerializer(new_job).data if new_job else None
                })
            except Exception as e:
                logger.error(f"Failed to retry job {job.id}: {e}")
                return Response({'error': str(e)}, status=500)
        else:
            return Response({'error': f'Cannot retry job with status {job.status}'}, status=400)

    else:
        return Response({'error': 'Unknown action. Use cancel or retry.'}, status=400)


@api_view(['GET'])
@permission_classes([CanExportData, AdminIPAllowlist])
@throttle_classes([AdminExportThrottle])
def export_jobs(request):
    """
    Export jobs to CSV.

    Security:
        - Requires export permission
        - Rate limited to 5/hour
    """
    jobs = IndexingJob.objects.all().order_by('-created_at')

    # Apply filters
    status_filter = request.query_params.get('status')
    if status_filter:
        jobs = jobs.filter(status=status_filter)

    search = request.query_params.get('search')
    if search:
        site_ids = Site.objects.filter(domain__icontains=search).values_list('id', flat=True)
        jobs = jobs.filter(Q(site_id__in=site_ids) | Q(url__icontains=search))

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'ID', 'Site Domain', 'Organization', 'Status', 'URL',
        'Max Pages', 'URLs Collected', 'URLs Processed', 'Documents Indexed',
        'Duration (s)', 'Error Message', 'Created At', 'Completed At'
    ])

    # Cache org and site lookups
    site_cache = {str(s.id): s.domain for s in Site.objects.all()}
    org_cache = {str(o.id): o.name for o in Organization.objects.all()}

    # Data rows
    for job in jobs[:5000]:  # Limit to 5000 rows
        writer.writerow([
            str(job.id),
            site_cache.get(str(job.site_id), 'Unknown'),
            org_cache.get(str(job.org_id), '') if job.org_id else '',
            job.status,
            job.url,
            job.max_pages,
            job.urls_collected,
            job.urls_processed,
            job.documents_indexed,
            job.duration if hasattr(job, 'duration') else '',
            job.error_message[:200] if job.error_message else '',
            job.created_at.isoformat() if job.created_at else '',
            job.completed_at.isoformat() if job.completed_at else ''
        ])

    # Log export action
    AdminAuditLog.log(
        admin=request.user,
        action='export.jobs',
        target_type='indexing_jobs',
        target_label=f'{min(jobs.count(), 5000)} jobs exported',
        request=request
    )

    # Return CSV response
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="jobs_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    return response


@api_view(['GET'])
@permission_classes([IsAdminUser])
def all_chatbots(request):
    """List all chatbots across the platform"""
    chatbots = Chatbot.objects.all().order_by('-created_at')
    
    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        chatbots = chatbots.filter(status=status_filter)
    
    site_id = request.query_params.get('site_id')
    if site_id:
        chatbots = chatbots.filter(site_id=site_id)
    
    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = chatbots.count()
    chatbots = chatbots[offset:offset + limit]
    
    serializer = ChatbotAdminSerializer(chatbots, many=True)
    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def all_sites(request):
    """List all sites across the platform"""
    sites = Site.objects.all().order_by('-created_at')
    
    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        sites = sites.filter(status=status_filter)
    
    org_id = request.query_params.get('org_id')
    if org_id:
        sites = sites.filter(org_id=org_id)
    
    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = sites.count()
    sites = sites[offset:offset + limit]
    
    serializer = SiteAdminSerializer(sites, many=True)
    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset
    })


# =====================
# Audit Logs Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser])
def audit_logs(request):
    """List all admin audit logs with filtering"""
    logs = AdminAuditLog.objects.all()
    
    # Filters
    action_filter = request.query_params.get('action')
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    
    admin_email = request.query_params.get('admin_email')
    if admin_email:
        logs = logs.filter(admin_email__icontains=admin_email)
    
    target_type = request.query_params.get('target_type')
    if target_type:
        logs = logs.filter(target_type=target_type)
    
    target_id = request.query_params.get('target_id')
    if target_id:
        logs = logs.filter(target_id=target_id)
    
    # Date range filter
    date_from = request.query_params.get('date_from')
    if date_from:
        logs = logs.filter(created_at__gte=date_from)
    
    date_to = request.query_params.get('date_to')
    if date_to:
        logs = logs.filter(created_at__lte=date_to)
    
    # Search query
    search = request.query_params.get('search')
    if search:
        logs = logs.filter(
            Q(admin_email__icontains=search) |
            Q(target_label__icontains=search) |
            Q(action__icontains=search)
        )
    
    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = logs.count()
    logs = logs[offset:offset + limit]
    
    serializer = AdminAuditLogSerializer(logs, many=True)
    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset
    })


# =====================
# Bulk Actions Endpoints
# =====================

@api_view(['POST'])
@permission_classes([CanPerformBulkOperations, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def bulk_user_action(request):
    """
    Perform bulk actions on multiple users.

    Security:
        - Requires bulk operations permission
        - Rate limited to 10/hour
        - All actions are logged
    """
    serializer = BulkActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    user_ids = serializer.validated_data['user_ids']
    action_type = serializer.validated_data['action']
    
    users = User.objects.filter(id__in=user_ids)
    affected_count = 0
    
    for user in users:
        if action_type == 'suspend':
            user.status = 'suspended'
            user.is_active = False
            user.save()
        elif action_type == 'activate':
            user.status = 'active'
            user.is_active = True
            user.save()
        elif action_type == 'delete':
            user.status = 'inactive'
            user.is_active = False
            user.save()
        affected_count += 1
    
    # Log the bulk action
    AdminAuditLog.log(
        admin=request.user,
        action=f'bulk.{action_type}',
        target_type='users',
        target_id='',
        target_label=f'{affected_count} users',
        details={'user_ids': [str(uid) for uid in user_ids]},
        request=request
    )
    
    return Response({
        'status': 'success',
        'action': action_type,
        'affected_count': affected_count
    })


# =====================
# Export Endpoints
# =====================

@api_view(['GET'])
@permission_classes([CanExportData, AdminIPAllowlist])
@throttle_classes([AdminExportThrottle])
def export_users(request):
    """
    Export users to CSV.

    Security:
        - Requires export permission
        - Rate limited to 5/hour to prevent data exfiltration
        - Action is logged
    """
    users = User.objects.all().order_by('-created_at')
    
    # Apply filters
    status_filter = request.query_params.get('status')
    if status_filter:
        users = users.filter(status=status_filter)
    
    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'ID', 'Email', 'Name', 'Status', 'Is Active', 'Is Staff',
        'Is Email Verified', 'Created At', 'Last Login'
    ])
    
    # Data rows
    for user in users:
        writer.writerow([
            str(user.id),
            user.email,
            user.name or '',
            user.status,
            user.is_active,
            user.is_staff,
            user.is_email_verified,
            user.created_at.isoformat() if user.created_at else '',
            user.last_login.isoformat() if user.last_login else ''
        ])
    
    # Log export action
    AdminAuditLog.log(
        admin=request.user,
        action='export.users',
        target_type='users',
        target_label=f'{users.count()} users exported',
        request=request
    )
    
    # Return CSV response
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="users_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    return response


# =====================
# Impersonation Endpoint
# =====================

@api_view(['POST'])
@permission_classes([CanImpersonate, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def impersonate_user(request, user_id):
    """
    Generate a temporary impersonation token for a user.

    Security measures:
        - Requires CanImpersonate permission (superuser or explicit permission)
        - Rate limited to 10/hour
        - Short token expiry (15 minutes)
        - Full audit logging
        - IP allowlist check
    """
    from rest_framework_simplejwt.tokens import RefreshToken

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=404)

    # Prevent impersonating other admins (security measure)
    if user.is_staff and not request.user.is_superuser:
        return Response(
            {'error': 'Cannot impersonate admin users. Superuser required.'},
            status=status.HTTP_403_FORBIDDEN
        )

    # Generate tokens for the target user
    refresh = RefreshToken.for_user(user)

    # Add impersonation claim to identify this as an impersonated session
    refresh['is_impersonated'] = True
    refresh['impersonated_by'] = str(request.user.id)
    refresh['impersonated_by_email'] = request.user.email

    # Set shorter expiry for impersonation tokens (15 minutes)
    IMPERSONATION_EXPIRY_MINUTES = 15
    refresh.access_token.set_exp(lifetime=timedelta(minutes=IMPERSONATION_EXPIRY_MINUTES))

    # Log the impersonation
    AdminAuditLog.log(
        admin=request.user,
        action='user.impersonate',
        target_type='user',
        target_id=str(user.id),
        target_label=user.email,
        request=request,
        details={
            'reason': request.data.get('reason', 'Not provided'),
            'expiry_minutes': IMPERSONATION_EXPIRY_MINUTES
        }
    )

    logger.warning(
        f"Admin {request.user.email} impersonating user {user.email}",
        extra={
            'admin_id': str(request.user.id),
            'target_id': str(user.id),
            'reason': request.data.get('reason', 'Not provided')
        }
    )

    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user_email': user.email,
        'user_id': str(user.id),
        'expires_in': IMPERSONATION_EXPIRY_MINUTES * 60,  # 15 minutes in seconds
        'warning': 'This is a time-limited impersonation session. Use responsibly.'
    })


# =====================
# System Health Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_health(request):
    """Get comprehensive system health status"""
    from apps.admin_api.services import SystemHealthService

    health_data = SystemHealthService.get_full_health_status()
    return Response(health_data)


@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_queues(request):
    """Get job queue status"""
    from apps.admin_api.services import SystemHealthService

    queue_data = SystemHealthService.get_queue_status()
    return Response(queue_data)


@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_metrics(request):
    """Get system usage metrics"""
    from apps.admin_api.services import SystemMetricsService

    metrics = SystemMetricsService.get_usage_metrics()
    return Response(metrics)


# =====================
# Maintenance Mode Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
def get_maintenance_mode(request):
    """Get current maintenance mode status"""
    from django.core.cache import cache
    
    maintenance_data = cache.get('maintenance_mode', {
        'enabled': False,
        'message': '',
        'estimated_end': None,
        'allowed_ips': []
    })
    
    return Response(maintenance_data)


@api_view(['POST'])
@permission_classes([IsSuperAdmin, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def set_maintenance_mode(request):
    """
    Enable or disable maintenance mode.
    
    Request body:
        - enabled: bool (required)
        - message: str (optional, displayed to users)
        - estimated_end: datetime (optional)
        - allowed_ips: list of IPs that can bypass maintenance (optional)
    """
    from django.core.cache import cache
    
    enabled = request.data.get('enabled', False)
    message = request.data.get('message', 'We are currently performing scheduled maintenance. Please check back soon.')
    estimated_end = request.data.get('estimated_end')
    allowed_ips = request.data.get('allowed_ips', [])
    
    maintenance_data = {
        'enabled': enabled,
        'message': message,
        'estimated_end': estimated_end,
        'allowed_ips': allowed_ips,
        'updated_at': timezone.now().isoformat(),
        'updated_by': request.user.email
    }
    
    # Store in cache (persists across restarts if using Redis)
    cache.set('maintenance_mode', maintenance_data, timeout=None)  # No expiry
    
    # Log the action
    AdminAuditLog.log(
        admin=request.user,
        action='system.maintenance_mode',
        target_type='system',
        target_id='',
        target_label='Maintenance Mode',
        request=request,
        details={
            'enabled': enabled,
            'message': message,
            'estimated_end': estimated_end
        }
    )
    
    action_str = 'enabled' if enabled else 'disabled'
    logger.info(f"Maintenance mode {action_str} by {request.user.email}")
    
    return Response({
        'status': 'success',
        'maintenance_mode': maintenance_data,
        'message': f'Maintenance mode {action_str}'
    })


# =====================
# Error Log Viewer Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsSuperAdmin, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def admin_error_logs(request):
    """
    View application error logs.
    
    GET /v1/admin/logs/errors/
    
    Query params:
        - level: Filter by log level (ERROR, WARNING, INFO)
        - search: Search in log messages
        - limit: Number of logs to return (default 100, max 500)
        - offset: Pagination offset
    """
    import os
    import re
    from pathlib import Path
    
    log_level = request.query_params.get('level', 'ERROR').upper()
    search_query = request.query_params.get('search', '').lower()
    limit = min(int(request.query_params.get('limit', 100)), 500)
    offset = int(request.query_params.get('offset', 0))
    
    # Get log file path from settings or use default
    log_file = getattr(settings, 'LOG_FILE_PATH', None)
    if not log_file:
        log_file = Path(settings.BASE_DIR) / 'logs' / 'django.log'
    
    logs = []
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # Read last N lines efficiently (tail-like behavior)
                lines = f.readlines()[-5000:]  # Last 5000 lines max
                
                # Parse log entries
                log_pattern = re.compile(
                    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+'  # timestamp
                    r'(\w+)\s+'  # log level
                    r'(\S+)\s+'  # logger name
                    r'(.*)$',  # message
                    re.MULTILINE
                )
                
                current_entry = None
                for line in lines:
                    match = log_pattern.match(line.strip())
                    if match:
                        # New log entry
                        if current_entry:
                            # Check filters before adding
                            if (log_level == 'ALL' or current_entry['level'] == log_level):
                                if not search_query or search_query in current_entry['message'].lower():
                                    logs.append(current_entry)
                        
                        current_entry = {
                            'timestamp': match.group(1),
                            'level': match.group(2),
                            'logger': match.group(3),
                            'message': match.group(4)
                        }
                    elif current_entry:
                        # Continuation of previous entry (multiline)
                        current_entry['message'] += '\n' + line.strip()
                
                # Don't forget the last entry
                if current_entry:
                    if (log_level == 'ALL' or current_entry['level'] == log_level):
                        if not search_query or search_query in current_entry['message'].lower():
                            logs.append(current_entry)
        
        # Reverse to show newest first
        logs = logs[::-1]
        
        # Apply pagination
        total = len(logs)
        logs = logs[offset:offset + limit]
        
        return Response({
            'logs': logs,
            'total': total,
            'limit': limit,
            'offset': offset,
            'log_file': str(log_file) if os.path.exists(log_file) else None,
            'file_exists': os.path.exists(log_file)
        })
        
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return Response({
            'logs': [],
            'total': 0,
            'error': str(e),
            'log_file': str(log_file),
            'file_exists': os.path.exists(log_file) if log_file else False
        })


# =====================
# Waitlist/Upgrade Interest Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser])
def waitlist_list(request):
    """List all waitlist entries with filtering"""
    interests = UpgradeInterest.objects.select_related(
        'organization', 'user'
    ).order_by('-created_at')

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        interests = interests.filter(status=status_filter)

    plan_filter = request.query_params.get('interested_plan')
    if plan_filter:
        interests = interests.filter(interested_plan=plan_filter)

    source_filter = request.query_params.get('source')
    if source_filter:
        interests = interests.filter(source=source_filter)

    # Search
    search = request.query_params.get('search')
    if search:
        interests = interests.filter(
            Q(email__icontains=search) |
            Q(company_name__icontains=search) |
            Q(organization__name__icontains=search) |
            Q(user__email__icontains=search)
        )

    # Date range filter
    date_from = request.query_params.get('date_from')
    if date_from:
        interests = interests.filter(created_at__gte=date_from)

    date_to = request.query_params.get('date_to')
    if date_to:
        interests = interests.filter(created_at__lte=date_to)

    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = interests.count()
    interests = interests[offset:offset + limit]

    serializer = UpgradeInterestAdminSerializer(interests, many=True)

    # Also return stats
    stats = {
        'total': total,
        'pending': UpgradeInterest.objects.filter(status='pending').count(),
        'contacted': UpgradeInterest.objects.filter(status='contacted').count(),
        'converted': UpgradeInterest.objects.filter(status='converted').count(),
        'declined': UpgradeInterest.objects.filter(status='declined').count(),
        'premium_interest': UpgradeInterest.objects.filter(interested_plan='premium').count(),
        'enterprise_interest': UpgradeInterest.objects.filter(interested_plan='enterprise').count(),
    }

    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset,
        'stats': stats
    })


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def waitlist_detail(request, interest_id):
    """Get or update a specific waitlist entry"""
    try:
        interest = UpgradeInterest.objects.select_related(
            'organization', 'user'
        ).get(id=interest_id)
    except UpgradeInterest.DoesNotExist:
        return Response({'error': 'Interest not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = UpgradeInterestAdminSerializer(interest)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = UpgradeInterestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Update fields
        if 'status' in serializer.validated_data:
            old_status = interest.status
            interest.status = serializer.validated_data['status']

            # Set contacted_at if changing to contacted
            if interest.status == 'contacted' and old_status != 'contacted':
                interest.contacted_at = timezone.now()

        if 'notes' in serializer.validated_data:
            interest.notes = serializer.validated_data['notes']

        interest.save()

        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='waitlist.update',
            target_type='upgrade_interest',
            target_id=str(interest.id),
            target_label=f"{interest.email} - {interest.interested_plan}",
            details=serializer.validated_data,
            request=request
        )

        logger.info(f"Admin updated waitlist entry {interest.id}: {serializer.validated_data}")

        return Response(UpgradeInterestAdminSerializer(interest).data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def waitlist_stats(request):
    """Get waitlist statistics for dashboard"""
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    # Basic stats
    stats = {
        'total': UpgradeInterest.objects.count(),
        'by_status': dict(
            UpgradeInterest.objects.values('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        ),
        'by_plan': dict(
            UpgradeInterest.objects.values('interested_plan')
            .annotate(count=Count('id'))
            .values_list('interested_plan', 'count')
        ),
        'by_source': dict(
            UpgradeInterest.objects.values('source')
            .annotate(count=Count('id'))
            .values_list('source', 'count')
        ),
        'pending_count': UpgradeInterest.objects.filter(status='pending').count(),
        'conversion_rate': 0,
    }

    # Calculate conversion rate
    total = stats['total']
    converted = stats['by_status'].get('converted', 0)
    if total > 0:
        stats['conversion_rate'] = round((converted / total) * 100, 1)

    # Recent signups (last 7 days)
    from datetime import timedelta
    week_ago = timezone.now() - timedelta(days=7)
    stats['recent_signups'] = UpgradeInterest.objects.filter(
        created_at__gte=week_ago
    ).count()

    # Daily signups for chart (last 30 days)
    month_ago = timezone.now() - timedelta(days=30)
    daily_signups = (
        UpgradeInterest.objects
        .filter(created_at__gte=month_ago)
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )
    stats['daily_signups'] = [
        {'date': entry['date'].isoformat(), 'count': entry['count']}
        for entry in daily_signups
    ]

    return Response(stats)


# =====================
# Platform Analytics Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser])
def platform_analytics(request):
    """Get comprehensive platform analytics"""
    analytics = AdminStatsService.get_platform_analytics()
    return Response(analytics)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def tier_stats(request):
    """Get statistics by tier"""
    stats = AdminStatsService.get_tier_stats()
    return Response(stats)


# =====================
# Tier Configuration Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_tier_config(request):
    """Get current tier configuration"""
    tiers = {}
    for tier_name, config in TIER_FEATURES.items():
        tiers[tier_name] = {
            'name': config.get('name', tier_name.title()),
            'limits': config.get('limits', {}),
            'features': config.get('features', []),
            'price': config.get('price', 0),
        }
    return Response(tiers)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_org_tier(request, org_id):
    """Update an organization's tier"""
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

    new_tier = request.data.get('plan_tier')
    if new_tier not in ['basic', 'premium', 'enterprise']:
        return Response(
            {'error': 'Invalid tier. Must be basic, premium, or enterprise'},
            status=status.HTTP_400_BAD_REQUEST
        )

    old_tier = org.plan_tier
    org.plan_tier = new_tier
    org.save()

    # Log the action
    AdminAuditLog.log(
        admin=request.user,
        action='org.tier_update',
        target_type='organization',
        target_id=str(org.id),
        target_label=org.name,
        details={'old_tier': old_tier, 'new_tier': new_tier},
        request=request
    )

    logger.info(f"Admin updated org {org.id} tier from {old_tier} to {new_tier}")

    return Response({
        'status': 'success',
        'organization_id': str(org.id),
        'old_tier': old_tier,
        'new_tier': new_tier,
        'message': f'Organization tier updated to {new_tier}'
    })


# =====================
# Feedback Management Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser])
def feedback_list(request):
    """List all feedback submissions with filtering"""
    feedback = Feedback.objects.select_related('user', 'resolved_by').order_by('-created_at')

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        feedback = feedback.filter(status=status_filter)

    feedback_type = request.query_params.get('feedback_type')
    if feedback_type:
        feedback = feedback.filter(feedback_type=feedback_type)

    priority = request.query_params.get('priority')
    if priority:
        feedback = feedback.filter(priority=priority)

    # Search
    search = request.query_params.get('search')
    if search:
        feedback = feedback.filter(
            Q(subject__icontains=search) |
            Q(message__icontains=search) |
            Q(email__icontains=search) |
            Q(user__email__icontains=search)
        )

    # Date range filter
    date_from = request.query_params.get('date_from')
    if date_from:
        feedback = feedback.filter(created_at__gte=date_from)

    date_to = request.query_params.get('date_to')
    if date_to:
        feedback = feedback.filter(created_at__lte=date_to)

    # Get stats before pagination
    all_feedback = Feedback.objects.all()
    stats = {
        'total': all_feedback.count(),
        'pending': all_feedback.filter(status='pending').count(),
        'in_review': all_feedback.filter(status='in_review').count(),
        'in_progress': all_feedback.filter(status='in_progress').count(),
        'resolved': all_feedback.filter(status='resolved').count(),
        'by_type': {
            'bug': all_feedback.filter(feedback_type='bug').count(),
            'feature': all_feedback.filter(feedback_type='feature').count(),
            'general': all_feedback.filter(feedback_type='general').count(),
            'complaint': all_feedback.filter(feedback_type='complaint').count(),
            'praise': all_feedback.filter(feedback_type='praise').count(),
        },
        'by_priority': {
            'critical': all_feedback.filter(priority='critical').count(),
            'high': all_feedback.filter(priority='high').count(),
            'medium': all_feedback.filter(priority='medium').count(),
            'low': all_feedback.filter(priority='low').count(),
        }
    }

    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = feedback.count()
    feedback = feedback[offset:offset + limit]

    serializer = FeedbackListSerializer(feedback, many=True)
    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset,
        'stats': stats
    })


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def feedback_detail(request, feedback_id):
    """Get or update a specific feedback entry"""
    try:
        feedback = Feedback.objects.select_related('user', 'resolved_by').get(id=feedback_id)
    except Feedback.DoesNotExist:
        return Response({'error': 'Feedback not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = FeedbackDetailSerializer(feedback)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = FeedbackUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = feedback.status

        # Update fields
        if 'status' in serializer.validated_data:
            feedback.status = serializer.validated_data['status']
            # Set resolved info if changing to resolved
            if feedback.status == 'resolved' and old_status != 'resolved':
                feedback.resolved_at = timezone.now()
                feedback.resolved_by = request.user

        if 'priority' in serializer.validated_data:
            feedback.priority = serializer.validated_data['priority']

        if 'admin_notes' in serializer.validated_data:
            feedback.admin_notes = serializer.validated_data['admin_notes']

        feedback.save()

        # Send user notification if status changed
        new_status = feedback.status
        if old_status != new_status:
            try:
                admin_notes = serializer.validated_data.get('admin_notes')
                feedback_notification_service.send_status_update_notification(
                    feedback, old_status, new_status, admin_notes
                )
            except Exception as e:
                # Log but don't fail the request if notification fails
                logger.warning(f"Failed to send status update notification: {e}")

        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='feedback.update',
            target_type='feedback',
            target_id=str(feedback.id),
            target_label=f"{feedback.feedback_type}: {feedback.subject or feedback.message[:50]}",
            details=serializer.validated_data,
            request=request
        )

        logger.info(f"Admin updated feedback {feedback.id}: {serializer.validated_data}")

        return Response(FeedbackDetailSerializer(feedback).data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def feedback_stats(request):
    """Get feedback statistics for dashboard"""
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from datetime import timedelta

    # Basic stats
    stats = {
        'total': Feedback.objects.count(),
        'by_status': dict(
            Feedback.objects.values('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        ),
        'by_type': dict(
            Feedback.objects.values('feedback_type')
            .annotate(count=Count('id'))
            .values_list('feedback_type', 'count')
        ),
        'by_priority': dict(
            Feedback.objects.values('priority')
            .annotate(count=Count('id'))
            .values_list('priority', 'count')
        ),
        'pending_count': Feedback.objects.filter(status='pending').count(),
        'critical_unresolved': Feedback.objects.filter(
            priority='critical',
            status__in=['pending', 'in_review', 'in_progress']
        ).count(),
    }

    # Recent feedback (last 7 days)
    week_ago = timezone.now() - timedelta(days=7)
    stats['recent_count'] = Feedback.objects.filter(created_at__gte=week_ago).count()

    # Daily submissions for chart (last 30 days)
    month_ago = timezone.now() - timedelta(days=30)
    daily_submissions = (
        Feedback.objects
        .filter(created_at__gte=month_ago)
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )
    stats['daily_submissions'] = [
        {'date': entry['date'].isoformat(), 'count': entry['count']}
        for entry in daily_submissions
    ]

    # Resolution rate
    resolved = Feedback.objects.filter(status__in=['resolved', 'closed']).count()
    if stats['total'] > 0:
        stats['resolution_rate'] = round((resolved / stats['total']) * 100, 1)
    else:
        stats['resolution_rate'] = 0

    return Response(stats)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def feedback_export(request):
    """Export feedback to CSV"""
    # Get filters from query params
    status_filter = request.query_params.get('status')
    type_filter = request.query_params.get('type')
    priority_filter = request.query_params.get('priority')
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')

    queryset = Feedback.objects.select_related('user', 'resolved_by').order_by('-created_at')

    # Apply filters
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if type_filter:
        queryset = queryset.filter(feedback_type=type_filter)
    if priority_filter:
        queryset = queryset.filter(priority=priority_filter)
    if start_date:
        queryset = queryset.filter(created_at__date__gte=start_date)
    if end_date:
        queryset = queryset.filter(created_at__date__lte=end_date)

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="feedback_export.csv"'

    writer = csv.writer(response)

    # Write header row
    writer.writerow([
        'ID',
        'Type',
        'Priority',
        'Status',
        'Subject',
        'Message',
        'User Email',
        'Steps to Reproduce',
        'Expected Behavior',
        'Actual Behavior',
        'Admin Notes',
        'Submitted At',
        'Resolved At',
        'Resolved By'
    ])

    # Write data rows
    for feedback in queryset:
        writer.writerow([
            str(feedback.id),
            feedback.feedback_type,
            feedback.priority,
            feedback.status,
            feedback.subject or '',
            feedback.message,
            feedback.user.email if feedback.user else (feedback.email or ''),
            feedback.steps_to_reproduce or '',
            feedback.expected_behavior or '',
            feedback.actual_behavior or '',
            feedback.admin_notes or '',
            feedback.created_at.strftime('%Y-%m-%d %H:%M:%S') if feedback.created_at else '',
            feedback.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if feedback.resolved_at else '',
            feedback.resolved_by.email if feedback.resolved_by else ''
        ])

    # Log the export
    AdminAuditLog.log(
        admin=request.user,
        action='feedback.export',
        target_type='feedback',
        target_id='bulk',
        target_label=f'Exported {queryset.count()} feedback items',
        details={
            'count': queryset.count(),
            'filters': {
                'status': status_filter,
                'type': type_filter,
                'priority': priority_filter,
                'start_date': start_date,
                'end_date': end_date
            }
        },
        request=request
    )

    return response


@api_view(['POST'])
@permission_classes([IsAdminUser])
def feedback_bulk_action(request):
    """Perform bulk actions on feedback items"""
    feedback_ids = request.data.get('feedback_ids', [])
    action = request.data.get('action')
    new_status = request.data.get('status')
    admin_notes = request.data.get('admin_notes')

    if not feedback_ids:
        return Response(
            {'error': 'No feedback IDs provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if action not in ['update_status', 'delete']:
        return Response(
            {'error': 'Invalid action. Allowed: update_status, delete'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if action == 'update_status' and not new_status:
        return Response(
            {'error': 'Status is required for update_status action'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate status value
    valid_statuses = ['pending', 'in_review', 'in_progress', 'resolved', 'closed', 'wont_fix']
    if action == 'update_status' and new_status not in valid_statuses:
        return Response(
            {'error': f'Invalid status. Allowed: {", ".join(valid_statuses)}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    feedback_items = Feedback.objects.filter(id__in=feedback_ids)
    count = feedback_items.count()

    if count == 0:
        return Response(
            {'error': 'No valid feedback items found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if action == 'update_status':
        # Track status changes for notifications
        changes = []
        for feedback in feedback_items:
            old_status = feedback.status
            if old_status != new_status:
                changes.append({
                    'feedback': feedback,
                    'old_status': old_status
                })

        # Update all items
        update_fields = {'status': new_status}
        if new_status == 'resolved':
            update_fields['resolved_at'] = timezone.now()
            update_fields['resolved_by'] = request.user
        if admin_notes:
            update_fields['admin_notes'] = admin_notes

        feedback_items.update(**update_fields)

        # Send notifications for status changes
        for change in changes:
            try:
                # Refresh from DB to get updated values
                change['feedback'].refresh_from_db()
                feedback_notification_service.send_status_update_notification(
                    change['feedback'],
                    change['old_status'],
                    new_status,
                    admin_notes
                )
            except Exception as e:
                logger.warning(f"Failed to send bulk status notification: {e}")

        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='feedback.bulk_update',
            target_type='feedback',
            target_id='bulk',
            target_label=f'Bulk status update: {count} items to {new_status}',
            details={
                'count': count,
                'new_status': new_status,
                'feedback_ids': [str(fid) for fid in feedback_ids]
            },
            request=request
        )

        return Response({
            'success': True,
            'message': f'Updated {count} feedback items to {new_status}',
            'count': count
        })

    elif action == 'delete':
        # Delete the feedback items
        feedback_items.delete()

        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='feedback.bulk_delete',
            target_type='feedback',
            target_id='bulk',
            target_label=f'Bulk delete: {count} items',
            details={
                'count': count,
                'feedback_ids': [str(fid) for fid in feedback_ids]
            },
            request=request
        )

        return Response({
            'success': True,
            'message': f'Deleted {count} feedback items',
            'count': count
        })


# =====================
# FAQ Category Endpoints
# =====================

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def faq_categories(request):
    """List or create FAQ categories"""
    if request.method == 'GET':
        categories = FAQCategory.objects.all().order_by('order', 'name')
        serializer = FAQCategorySerializer(categories, many=True)
        return Response({
            'results': serializer.data,
            'count': categories.count()
        })

    elif request.method == 'POST':
        serializer = FAQCategoryCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='faq_category.create',
            target_type='faq_category',
            target_id=str(category.id),
            target_label=category.name,
            request=request
        )

        logger.info(f"Admin created FAQ category {category.id}: {category.name}")
        return Response(FAQCategorySerializer(category).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def faq_category_detail(request, category_id):
    """Get, update, or delete a FAQ category"""
    try:
        category = FAQCategory.objects.get(id=category_id)
    except FAQCategory.DoesNotExist:
        return Response({'error': 'Category not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = FAQCategorySerializer(category)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = FAQCategoryCreateUpdateSerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        category = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='faq_category.update',
            target_type='faq_category',
            target_id=str(category.id),
            target_label=category.name,
            request=request
        )

        return Response(FAQCategorySerializer(category).data)

    elif request.method == 'DELETE':
        category_name = category.name
        category_id_str = str(category.id)
        category.delete()

        AdminAuditLog.log(
            admin=request.user,
            action='faq_category.delete',
            target_type='faq_category',
            target_id=category_id_str,
            target_label=category_name,
            request=request
        )

        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)


# =====================
# FAQ Endpoints
# =====================

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def faqs_list(request):
    """List or create FAQs"""
    if request.method == 'GET':
        faqs = FAQ.objects.select_related('category').order_by('category__order', 'order')

        # Filters
        category_id = request.query_params.get('category')
        if category_id:
            faqs = faqs.filter(category_id=category_id)

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            faqs = faqs.filter(is_active=is_active.lower() == 'true')

        is_featured = request.query_params.get('is_featured')
        if is_featured is not None:
            faqs = faqs.filter(is_featured=is_featured.lower() == 'true')

        # Search
        search = request.query_params.get('search')
        if search:
            faqs = faqs.filter(
                Q(question__icontains=search) |
                Q(answer__icontains=search)
            )

        # Pagination
        limit = min(int(request.query_params.get('limit', 50)), 100)
        offset = int(request.query_params.get('offset', 0))
        total = faqs.count()
        faqs = faqs[offset:offset + limit]

        serializer = FAQSerializer(faqs, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'limit': limit,
            'offset': offset
        })

    elif request.method == 'POST':
        serializer = FAQCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        faq = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='faq.create',
            target_type='faq',
            target_id=str(faq.id),
            target_label=faq.question[:100],
            request=request
        )

        logger.info(f"Admin created FAQ {faq.id}")
        return Response(FAQSerializer(faq).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def faq_detail(request, faq_id):
    """Get, update, or delete a FAQ"""
    try:
        faq = FAQ.objects.select_related('category').get(id=faq_id)
    except FAQ.DoesNotExist:
        return Response({'error': 'FAQ not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = FAQSerializer(faq)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = FAQCreateUpdateSerializer(faq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        faq = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='faq.update',
            target_type='faq',
            target_id=str(faq.id),
            target_label=faq.question[:100],
            request=request
        )

        return Response(FAQSerializer(faq).data)

    elif request.method == 'DELETE':
        faq_question = faq.question[:100]
        faq_id_str = str(faq.id)
        faq.delete()

        AdminAuditLog.log(
            admin=request.user,
            action='faq.delete',
            target_type='faq',
            target_id=faq_id_str,
            target_label=faq_question,
            request=request
        )

        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)


# =====================
# Help Article Endpoints
# =====================

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def help_articles_list(request):
    """List or create help articles"""
    if request.method == 'GET':
        articles = HelpArticle.objects.select_related('category').order_by('category__order', 'order', 'title')

        # Filters
        category_id = request.query_params.get('category')
        if category_id:
            articles = articles.filter(category_id=category_id)

        article_type = request.query_params.get('article_type')
        if article_type:
            articles = articles.filter(article_type=article_type)

        is_active = request.query_params.get('is_active')
        if is_active is not None:
            articles = articles.filter(is_active=is_active.lower() == 'true')

        is_featured = request.query_params.get('is_featured')
        if is_featured is not None:
            articles = articles.filter(is_featured=is_featured.lower() == 'true')

        # Search
        search = request.query_params.get('search')
        if search:
            articles = articles.filter(
                Q(title__icontains=search) |
                Q(summary__icontains=search) |
                Q(content__icontains=search)
            )

        # Pagination
        limit = min(int(request.query_params.get('limit', 50)), 100)
        offset = int(request.query_params.get('offset', 0))
        total = articles.count()
        articles = articles[offset:offset + limit]

        serializer = HelpArticleListSerializer(articles, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'limit': limit,
            'offset': offset
        })

    elif request.method == 'POST':
        serializer = HelpArticleCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='help_article.create',
            target_type='help_article',
            target_id=str(article.id),
            target_label=article.title,
            request=request
        )

        logger.info(f"Admin created help article {article.id}: {article.title}")
        return Response(HelpArticleDetailSerializer(article).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def help_article_detail(request, article_id):
    """Get, update, or delete a help article"""
    try:
        article = HelpArticle.objects.select_related('category').prefetch_related('related_articles').get(id=article_id)
    except HelpArticle.DoesNotExist:
        return Response({'error': 'Article not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = HelpArticleDetailSerializer(article)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = HelpArticleCreateUpdateSerializer(article, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        article = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='help_article.update',
            target_type='help_article',
            target_id=str(article.id),
            target_label=article.title,
            request=request
        )

        return Response(HelpArticleDetailSerializer(article).data)

    elif request.method == 'DELETE':
        article_title = article.title
        article_id_str = str(article.id)
        article.delete()

        AdminAuditLog.log(
            admin=request.user,
            action='help_article.delete',
            target_type='help_article',
            target_id=article_id_str,
            target_label=article_title,
            request=request
        )

        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def help_center_stats(request):
    """Get help center statistics"""
    from django.db.models import Sum

    stats = {
        'total_categories': FAQCategory.objects.filter(is_active=True).count(),
        'total_faqs': FAQ.objects.filter(is_active=True).count(),
        'total_articles': HelpArticle.objects.filter(is_active=True).count(),
        'featured_faqs': FAQ.objects.filter(is_featured=True, is_active=True).count(),
        'featured_articles': HelpArticle.objects.filter(is_featured=True, is_active=True).count(),
        'total_faq_views': FAQ.objects.aggregate(total=Sum('view_count'))['total'] or 0,
        'total_article_views': HelpArticle.objects.aggregate(total=Sum('view_count'))['total'] or 0,
        'faq_helpful_ratio': None,
        'article_helpful_ratio': None,
    }

    # Calculate helpfulness ratios
    faq_helpful = FAQ.objects.aggregate(
        helpful=Sum('helpful_count'),
        not_helpful=Sum('not_helpful_count')
    )
    if faq_helpful['helpful'] and (faq_helpful['helpful'] + (faq_helpful['not_helpful'] or 0)) > 0:
        total = faq_helpful['helpful'] + (faq_helpful['not_helpful'] or 0)
        stats['faq_helpful_ratio'] = round(faq_helpful['helpful'] / total * 100, 1)

    article_helpful = HelpArticle.objects.aggregate(
        helpful=Sum('helpful_count'),
        not_helpful=Sum('not_helpful_count')
    )
    if article_helpful['helpful'] and (article_helpful['helpful'] + (article_helpful['not_helpful'] or 0)) > 0:
        total = article_helpful['helpful'] + (article_helpful['not_helpful'] or 0)
        stats['article_helpful_ratio'] = round(article_helpful['helpful'] / total * 100, 1)

    # Top viewed FAQs
    stats['top_faqs'] = list(
        FAQ.objects.filter(is_active=True)
        .order_by('-view_count')[:5]
        .values('id', 'question', 'view_count', 'helpful_count')
    )

    # Top viewed articles
    stats['top_articles'] = list(
        HelpArticle.objects.filter(is_active=True)
        .order_by('-view_count')[:5]
        .values('id', 'title', 'view_count', 'helpful_count')
    )

    return Response(stats)


# =====================
# Admin Leads Dashboard
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_leads_dashboard(request):
    """
    GET /v1/admin/leads/
    
    Platform-wide leads dashboard for admins.
    Shows leads across ALL organizations.
    
    Query params:
    - days: Number of days to look back (default 30)
    - org_id: Filter by specific organization
    - chatbot_id: Filter by specific chatbot
    - priority: Filter by priority (hot, warm, cold)
    - limit: Number of leads to return (default 50)
    - offset: Pagination offset
    """
    from django.db.models import Count, Avg, Q, Case, When, Value, CharField
    from django.utils import timezone
    from datetime import timedelta
    from apps.analytics.models import LeadScore
    from apps.organizations.models import Organization
    from apps.analytics.serializers import LeadScoreListSerializer
    
    try:
        # Parse query params - no tier restrictions for admin
        days = int(request.query_params.get('days', 30))
        org_id = request.query_params.get('org_id')
        chatbot_id = request.query_params.get('chatbot_id')
        priority = request.query_params.get('priority')
        limit = int(request.query_params.get('limit', 50))
        offset = int(request.query_params.get('offset', 0))
        
        # Calculate date range
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Base queryset - ALL leads platform-wide
        leads_qs = LeadScore.objects.filter(
            session_date__gte=start_date,
            session_date__lte=end_date
        ).select_related('chatbot', 'session', 'org')
        
        # Apply optional filters
        if org_id:
            leads_qs = leads_qs.filter(org_id=org_id)
        if chatbot_id:
            leads_qs = leads_qs.filter(chatbot_id=chatbot_id)
        if priority:
            leads_qs = leads_qs.filter(priority=priority)
        
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
        summary['ai_analyzed'] = leads_qs.filter(llm_insights__isnull=False).count()
        
        # Get intent breakdown
        intent_breakdown = list(
            leads_qs.exclude(detected_intent__isnull=True)
            .values('detected_intent')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        # Get daily trend
        daily_trend = {}
        daily_data = list(
            leads_qs.values('session_date', 'priority')
            .annotate(count=Count('id'))
            .order_by('session_date')
        )
        for item in daily_data:
            date_key = item['session_date'].isoformat()
            if date_key not in daily_trend:
                daily_trend[date_key] = {'date': date_key, 'total': 0, 'hot': 0, 'warm': 0, 'cold': 0}
            daily_trend[date_key][item['priority']] = item['count']
            daily_trend[date_key]['total'] += item['count']
        
        # Get geo distribution
        geo_distribution = dict(
            leads_qs.exclude(geo_location__isnull=True)
            .exclude(geo_location='')
            .values_list('geo_location')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        # Get device breakdown
        device_breakdown = dict(
            leads_qs.values_list('device_type')
            .annotate(count=Count('id'))
        )
        
        # Get organization breakdown (admin-specific)
        org_breakdown = list(
            leads_qs.values('org__name', 'org_id')
            .annotate(
                total=Count('id'),
                hot=Count('id', filter=Q(priority='hot')),
                warm=Count('id', filter=Q(priority='warm')),
                cold=Count('id', filter=Q(priority='cold')),
                avg_score=Avg('total_score')
            )
            .order_by('-total')[:10]
        )
        
        # Get chatbot comparison
        chatbot_comparison = list(
            leads_qs.values('chatbot__id', 'chatbot__name')
            .annotate(
                total=Count('id'),
                hot=Count('id', filter=Q(priority='hot')),
                warm=Count('id', filter=Q(priority='warm')),
                avg_score=Avg('total_score')
            )
            .order_by('-total')[:10]
        )
        
        # Get score distribution
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
        
        # Get quality trends
        quality_data = list(
            leads_qs.values('session_date')
            .annotate(
                avg_score=Avg('total_score'),
                total=Count('id'),
                hot_count=Count('id', filter=Q(priority='hot'))
            )
            .order_by('session_date')
        )
        quality_trends = []
        for item in quality_data:
            hot_rate = (item['hot_count'] / item['total'] * 100) if item['total'] > 0 else 0
            quality_trends.append({
                'date': item['session_date'].isoformat(),
                'avg_score': round(item['avg_score'] or 0, 1),
                'hot_rate': round(hot_rate, 1)
            })
        
        # Get paginated leads with org info
        leads = leads_qs.order_by('-total_score')[offset:offset + limit]
        leads_data = LeadScoreListSerializer(leads, many=True).data
        
        # Add org name to each lead
        for i, lead in enumerate(leads):
            if lead.org:
                leads_data[i]['organization'] = {
                    'id': str(lead.org.id),
                    'name': lead.org.name
                }
        
        return Response({
            'summary': summary,
            'leads': leads_data,
            'intent_breakdown': intent_breakdown,
            'daily_trend': list(daily_trend.values()),
            'geo_distribution': geo_distribution,
            'device_breakdown': device_breakdown,
            'org_breakdown': org_breakdown,
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
        })
        
    except Exception as e:
        logger.error(f"Error in admin_leads_dashboard: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch leads data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_query_analytics(request):
    """
    GET /v1/admin/leads/queries/
    
    Platform-wide query analytics for admins.
    Shows what users are asking across all organizations.
    """
    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta
    from apps.chat.models import ChatMessage, ChatSession
    
    try:
        days = int(request.query_params.get('days', 30))
        org_id = request.query_params.get('org_id')
        limit = int(request.query_params.get('limit', 20))
        
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Get user messages (questions)
        messages_qs = ChatMessage.objects.filter(
            role='user',
            created_at__gte=start_date,
            created_at__lte=end_date
        ).select_related('session')
        
        if org_id:
            messages_qs = messages_qs.filter(session__org_id=org_id)
        
        # Get top queries
        top_queries = list(
            messages_qs.values('content')
            .annotate(count=Count('id'))
            .order_by('-count')[:limit]
        )
        
        # Get query categories
        categories = list(
            messages_qs.exclude(query_category__isnull=True)
            .exclude(query_category='')
            .values('query_category')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        # Get unanswered queries (those with dislike feedback)
        unanswered = list(
            messages_qs.filter(
                session__messages__role='assistant',
                session__messages__feedback='dislike'
            ).values('content')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        return Response({
            'top_queries': top_queries,
            'categories': categories,
            'unanswered_queries': unanswered,
            'total_queries': messages_qs.count(),
            'period_days': days,
        })
        
    except Exception as e:
        logger.error(f"Error in admin_query_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch query analytics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_geo_analytics(request):
    """
    GET /v1/admin/leads/geo/
    
    Platform-wide geographic analytics for admins.
    """
    from django.db.models import Count
    from django.utils import timezone
    from datetime import timedelta
    from apps.chat.models import ChatSession
    
    try:
        days = int(request.query_params.get('days', 30))
        org_id = request.query_params.get('org_id')
        
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        sessions_qs = ChatSession.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        if org_id:
            sessions_qs = sessions_qs.filter(org_id=org_id)
        
        # Get country distribution
        countries = list(
            sessions_qs.exclude(geo_country_code__isnull=True)
            .exclude(geo_country_code='')
            .values('geo_country_code', 'geo_country_name')
            .annotate(count=Count('id'))
            .order_by('-count')[:20]
        )
        
        # Sessions with geo data
        sessions_with_geo = sessions_qs.exclude(geo_country_code__isnull=True).exclude(geo_country_code='').count()
        total_sessions = sessions_qs.count()
        
        return Response({
            'countries': countries,
            'geo_stats': {
                'sessions_with_geo': sessions_with_geo,
                'total_sessions': total_sessions,
                'geo_coverage': round(sessions_with_geo / total_sessions * 100, 1) if total_sessions > 0 else 0,
                'unique_countries': len(countries),
            },
            'period_days': days,
        })
        
    except Exception as e:
        logger.error(f"Error in admin_geo_analytics: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch geo analytics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =====================
# Two-Factor Authentication (2FA) Endpoints
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def twofa_status(request):
    """
    GET /v1/admin/auth/2fa/status/

    Get current 2FA status for the authenticated admin.
    """
    from apps.admin_api.models import Admin2FA

    try:
        twofa = Admin2FA.objects.get(user=request.user)
        return Response({
            'is_enabled': twofa.is_enabled,
            'enabled_at': twofa.enabled_at,
            'last_used_at': twofa.last_used_at,
            'backup_codes_remaining': len(twofa.backup_codes) if twofa.backup_codes else 0
        })
    except Admin2FA.DoesNotExist:
        return Response({
            'is_enabled': False,
            'enabled_at': None,
            'last_used_at': None,
            'backup_codes_remaining': 0
        })


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def twofa_setup(request):
    """
    POST /v1/admin/auth/2fa/setup/

    Initialize 2FA setup - generates secret and QR code.
    Returns the secret and QR code for the authenticator app.
    """
    from apps.admin_api.models import Admin2FA
    import qrcode
    import qrcode.image.svg
    from io import BytesIO
    import base64

    twofa = Admin2FA.get_or_create_for_user(request.user)

    # Generate new secret
    secret = twofa.generate_secret()
    twofa.is_verified = False
    twofa.save()

    # Get provisioning URI
    uri = twofa.get_totp_uri(issuer="Webbotify Admin")

    # Generate QR code as base64 PNG
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    logger.info(f"Admin {request.user.email} initiated 2FA setup")

    return Response({
        'secret': secret,
        'qr_code': f"data:image/png;base64,{qr_base64}",
        'provisioning_uri': uri,
        'message': 'Scan the QR code with your authenticator app, then verify with a code.'
    })


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminLoginThrottle])  # Use login throttle for verification
def twofa_verify(request):
    """
    POST /v1/admin/auth/2fa/verify/

    Verify TOTP code and enable 2FA.

    Request body:
        - code: 6-digit TOTP code from authenticator app
    """
    from apps.admin_api.models import Admin2FA
    from apps.admin_api.serializers import TwoFactorVerifySerializer

    serializer = TwoFactorVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    code = serializer.validated_data['code']

    try:
        twofa = Admin2FA.objects.get(user=request.user)
    except Admin2FA.DoesNotExist:
        return Response(
            {'error': '2FA setup not initiated. Call /2fa/setup/ first.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not twofa.secret:
        return Response(
            {'error': '2FA setup not initiated. Call /2fa/setup/ first.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Verify the code
    if not twofa.verify_code(code):
        logger.warning(f"Invalid 2FA code during setup for {request.user.email}")
        return Response(
            {'error': 'Invalid verification code. Please try again.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Generate backup codes
    backup_codes = twofa.generate_backup_codes(count=10)

    # Enable 2FA
    twofa.enable()

    # Log the action
    AdminAuditLog.log(
        admin=request.user,
        action='system.config_change',
        target_type='user',
        target_id=str(request.user.id),
        target_label=request.user.email,
        details={'action': '2fa_enabled'},
        request=request
    )

    logger.info(f"Admin {request.user.email} enabled 2FA")

    return Response({
        'message': '2FA has been enabled successfully.',
        'backup_codes': backup_codes,
        'warning': 'Save these backup codes securely. They will only be shown once.'
    })


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def twofa_disable(request):
    """
    POST /v1/admin/auth/2fa/disable/

    Disable 2FA for the admin account.

    Request body:
        - code: Current TOTP code or backup code
        - password: Current password for confirmation
    """
    from apps.admin_api.models import Admin2FA
    from apps.admin_api.serializers import TwoFactorDisableSerializer

    serializer = TwoFactorDisableSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    code = serializer.validated_data['code']
    password = serializer.validated_data['password']

    # Verify password
    if not request.user.check_password(password):
        return Response(
            {'error': 'Invalid password.'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        twofa = Admin2FA.objects.get(user=request.user)
    except Admin2FA.DoesNotExist:
        return Response(
            {'error': '2FA is not enabled.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not twofa.is_enabled:
        return Response(
            {'error': '2FA is not enabled.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Verify code (TOTP or backup)
    code_valid = twofa.verify_code(code) or twofa.verify_backup_code(code)
    if not code_valid:
        logger.warning(f"Invalid code during 2FA disable for {request.user.email}")
        return Response(
            {'error': 'Invalid verification code.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Disable 2FA
    twofa.disable()

    # Log the action
    AdminAuditLog.log(
        admin=request.user,
        action='system.config_change',
        target_type='user',
        target_id=str(request.user.id),
        target_label=request.user.email,
        details={'action': '2fa_disabled'},
        request=request
    )

    logger.info(f"Admin {request.user.email} disabled 2FA")

    return Response({
        'message': '2FA has been disabled.'
    })


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def twofa_regenerate_backup_codes(request):
    """
    POST /v1/admin/auth/2fa/backup-codes/

    Regenerate backup codes (requires current TOTP code).

    Request body:
        - code: Current TOTP code for verification
    """
    from apps.admin_api.models import Admin2FA
    from apps.admin_api.serializers import TwoFactorVerifySerializer

    serializer = TwoFactorVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    code = serializer.validated_data['code']

    try:
        twofa = Admin2FA.objects.get(user=request.user)
    except Admin2FA.DoesNotExist:
        return Response(
            {'error': '2FA is not enabled.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not twofa.is_enabled:
        return Response(
            {'error': '2FA is not enabled.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Verify TOTP code
    if not twofa.verify_code(code):
        return Response(
            {'error': 'Invalid verification code.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Generate new backup codes
    backup_codes = twofa.generate_backup_codes(count=10)
    twofa.save()

    # Log the action
    AdminAuditLog.log(
        admin=request.user,
        action='system.config_change',
        target_type='user',
        target_id=str(request.user.id),
        target_label=request.user.email,
        details={'action': '2fa_backup_codes_regenerated'},
        request=request
    )

    logger.info(f"Admin {request.user.email} regenerated 2FA backup codes")

    return Response({
        'backup_codes': backup_codes,
        'message': 'New backup codes generated. Save them securely.',
        'warning': 'Previous backup codes are now invalid.'
    })


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AdminLoginThrottle, AdminLoginDailyThrottle])
def twofa_login_verify(request):
    """
    POST /v1/admin/auth/2fa/login/

    Verify 2FA code during admin login.

    This endpoint is called after initial credentials are verified
    when the user has 2FA enabled.

    Request body:
        - temp_token: Temporary token from initial login
        - code: 6-digit TOTP code or backup code
    """
    from apps.admin_api.models import Admin2FA
    from apps.admin_api.serializers import TwoFactorLoginSerializer, AdminUserSerializer
    from django.core.cache import cache

    serializer = TwoFactorLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    temp_token = serializer.validated_data['temp_token']
    code = serializer.validated_data['code']

    # Retrieve user ID from temp token
    cache_key = f'admin_2fa_pending_{temp_token}'
    user_data = cache.get(cache_key)

    if not user_data:
        return Response(
            {'error': 'Invalid or expired token. Please login again.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.get(id=user_data['user_id'])
    except User.DoesNotExist:
        return Response(
            {'error': 'User not found.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        twofa = Admin2FA.objects.get(user=user)
    except Admin2FA.DoesNotExist:
        return Response(
            {'error': '2FA is not configured.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Verify code (TOTP or backup)
    code_valid = False
    is_backup_code = False

    if len(code) == 6 and code.isdigit():
        code_valid = twofa.verify_code(code)
    else:
        # Try as backup code
        code_valid = twofa.verify_backup_code(code)
        is_backup_code = True

    if not code_valid:
        logger.warning(f"Invalid 2FA code during login for {user.email}")
        return Response(
            {'error': 'Invalid verification code.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Record 2FA use
    twofa.record_use()

    # Clear the temp token
    cache.delete(cache_key)

    # Generate final tokens
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token

    # Add admin claims
    access_token['is_admin'] = True
    access_token['is_superuser'] = user.is_superuser
    access_token['is_staff'] = user.is_staff

    # Get client info for logging
    client_ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

    # Record successful login
    LoginHistory.objects.create(
        user=user,
        success=True,
        ip_address=client_ip,
        user_agent=user_agent
    )

    # Log the admin login
    AdminAuditLog.objects.create(
        admin=user,
        admin_email=user.email,
        action='system.config_change',
        target_type='user',
        target_id=str(user.id),
        target_label=user.email,
        ip_address=client_ip,
        user_agent=user_agent,
        details={
            'login_method': 'admin_portal',
            'action': 'admin_login_2fa',
            'used_backup_code': is_backup_code
        }
    )

    # Update last login
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])

    logger.info(f"Admin 2FA login successful for {user.email}")

    response_data = {
        'user': AdminUserSerializer(user).data,
        'tokens': {
            'access': str(access_token),
            'refresh': str(refresh),
        },
        'is_admin': True
    }

    if is_backup_code:
        response_data['warning'] = f'You used a backup code. {len(twofa.backup_codes)} codes remaining.'

    return Response(response_data)


# =====================
# Alerting System Endpoints
# =====================

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def alert_rules_list(request):
    """
    GET /v1/admin/alerts/rules/
    List all alert rules.

    POST /v1/admin/alerts/rules/
    Create a new alert rule.
    """
    from apps.admin_api.models import AlertRule
    from apps.admin_api.serializers import AlertRuleSerializer, AlertRuleCreateSerializer

    if request.method == 'GET':
        rules = AlertRule.objects.select_related('created_by').order_by('-created_at')

        # Filters
        alert_type = request.query_params.get('alert_type')
        if alert_type:
            rules = rules.filter(alert_type=alert_type)

        is_enabled = request.query_params.get('is_enabled')
        if is_enabled is not None:
            rules = rules.filter(is_enabled=is_enabled.lower() == 'true')

        severity = request.query_params.get('severity')
        if severity:
            rules = rules.filter(severity=severity)

        # Pagination
        limit = min(int(request.query_params.get('limit', 50)), 100)
        offset = int(request.query_params.get('offset', 0))
        total = rules.count()
        rules = rules[offset:offset + limit]

        serializer = AlertRuleSerializer(rules, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'limit': limit,
            'offset': offset
        })

    elif request.method == 'POST':
        serializer = AlertRuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save(created_by=request.user)

        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='alert_rule',
            target_id=str(rule.id),
            target_label=rule.name,
            details={'action': 'created', 'alert_type': rule.alert_type},
            request=request
        )

        logger.info(f"Admin {request.user.email} created alert rule {rule.id}: {rule.name}")
        return Response(AlertRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def alert_rule_detail(request, rule_id):
    """
    GET /v1/admin/alerts/rules/<rule_id>/
    Get alert rule details.

    PATCH /v1/admin/alerts/rules/<rule_id>/
    Update an alert rule.

    DELETE /v1/admin/alerts/rules/<rule_id>/
    Delete an alert rule.
    """
    from apps.admin_api.models import AlertRule
    from apps.admin_api.serializers import AlertRuleSerializer, AlertRuleCreateSerializer

    try:
        rule = AlertRule.objects.select_related('created_by').get(id=rule_id)
    except AlertRule.DoesNotExist:
        return Response({'error': 'Alert rule not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = AlertRuleSerializer(rule)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = AlertRuleCreateSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save()

        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='alert_rule',
            target_id=str(rule.id),
            target_label=rule.name,
            details={'action': 'updated', 'changes': request.data},
            request=request
        )

        return Response(AlertRuleSerializer(rule).data)

    elif request.method == 'DELETE':
        rule_name = rule.name
        rule_id_str = str(rule.id)
        rule.delete()

        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='alert_rule',
            target_id=rule_id_str,
            target_label=rule_name,
            details={'action': 'deleted'},
            request=request
        )

        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def alert_rule_test(request, rule_id):
    """
    POST /v1/admin/alerts/rules/<rule_id>/test/

    Test an alert rule by evaluating it immediately.
    """
    from apps.admin_api.models import AlertRule
    from apps.admin_api.services import AlertService

    try:
        rule = AlertRule.objects.get(id=rule_id)
    except AlertRule.DoesNotExist:
        return Response({'error': 'Alert rule not found'}, status=status.HTTP_404_NOT_FOUND)

    # Evaluate the rule
    result = AlertService.evaluate_rule(rule)

    return Response({
        'rule_name': rule.name,
        'alert_type': rule.alert_type,
        'triggered': result.get('triggered', False),
        'details': result.get('details', {}),
        'message': 'Rule evaluation complete. No notification sent during test.'
    })


@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def alert_notifications_list(request):
    """
    GET /v1/admin/alerts/notifications/

    List alert notifications history.
    """
    from apps.admin_api.models import AlertNotification
    from apps.admin_api.serializers import AlertNotificationSerializer

    notifications = AlertNotification.objects.select_related('rule').order_by('-sent_at')

    # Filters
    rule_id = request.query_params.get('rule_id')
    if rule_id:
        notifications = notifications.filter(rule_id=rule_id)

    severity = request.query_params.get('severity')
    if severity:
        notifications = notifications.filter(severity=severity)

    delivered = request.query_params.get('delivered')
    if delivered is not None:
        notifications = notifications.filter(delivered=delivered.lower() == 'true')

    # Date range
    start_date = request.query_params.get('start_date')
    if start_date:
        notifications = notifications.filter(sent_at__date__gte=start_date)

    end_date = request.query_params.get('end_date')
    if end_date:
        notifications = notifications.filter(sent_at__date__lte=end_date)

    # Pagination
    limit = min(int(request.query_params.get('limit', 50)), 100)
    offset = int(request.query_params.get('offset', 0))
    total = notifications.count()
    notifications = notifications[offset:offset + limit]

    serializer = AlertNotificationSerializer(notifications, many=True)
    return Response({
        'results': serializer.data,
        'count': total,
        'limit': limit,
        'offset': offset
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_alerts_list(request):
    """
    GET /v1/admin/alerts/system/
    List active system alerts for dashboard.

    POST /v1/admin/alerts/system/
    Create a manual system alert.
    """
    from apps.admin_api.models import SystemAlert
    from apps.admin_api.serializers import SystemAlertSerializer, SystemAlertCreateSerializer

    if request.method == 'GET':
        # By default, show active alerts
        show_all = request.query_params.get('all', 'false').lower() == 'true'

        if show_all:
            alerts = SystemAlert.objects.all()
        else:
            alerts = SystemAlert.get_active_alerts()

        # Filters
        level = request.query_params.get('level')
        if level:
            alerts = alerts.filter(level=level)

        acknowledged = request.query_params.get('acknowledged')
        if acknowledged is not None:
            alerts = alerts.filter(is_acknowledged=acknowledged.lower() == 'true')

        # Pagination
        limit = min(int(request.query_params.get('limit', 50)), 100)
        offset = int(request.query_params.get('offset', 0))
        total = alerts.count()
        alerts = alerts[offset:offset + limit]

        serializer = SystemAlertSerializer(alerts, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'limit': limit,
            'offset': offset
        })

    elif request.method == 'POST':
        serializer = SystemAlertCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.admin_api.services import AlertService
        alert = AlertService.create_manual_alert(
            title=serializer.validated_data['title'],
            message=serializer.validated_data['message'],
            level=serializer.validated_data.get('level', 'warning'),
            related_type=serializer.validated_data.get('related_type', ''),
            related_id=serializer.validated_data.get('related_id', ''),
            expires_hours=serializer.validated_data.get('expires_hours', 24)
        )

        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='system_alert',
            target_id=str(alert.id),
            target_label=alert.title,
            details={'action': 'created', 'level': alert.level},
            request=request
        )

        logger.info(f"Admin {request.user.email} created system alert: {alert.title}")
        return Response(SystemAlertSerializer(alert).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'DELETE'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_alert_detail(request, alert_id):
    """
    GET /v1/admin/alerts/system/<alert_id>/
    Get system alert details.

    DELETE /v1/admin/alerts/system/<alert_id>/
    Delete a system alert.
    """
    from apps.admin_api.models import SystemAlert
    from apps.admin_api.serializers import SystemAlertSerializer

    try:
        alert = SystemAlert.objects.get(id=alert_id)
    except SystemAlert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(SystemAlertSerializer(alert).data)

    elif request.method == 'DELETE':
        alert_title = alert.title
        alert_id_str = str(alert.id)
        alert.delete()

        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='system_alert',
            target_id=alert_id_str,
            target_label=alert_title,
            details={'action': 'deleted'},
            request=request
        )

        return Response({'status': 'deleted'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_alert_acknowledge(request, alert_id):
    """
    POST /v1/admin/alerts/system/<alert_id>/acknowledge/

    Acknowledge a system alert.
    """
    from apps.admin_api.models import SystemAlert
    from apps.admin_api.serializers import SystemAlertSerializer

    try:
        alert = SystemAlert.objects.get(id=alert_id)
    except SystemAlert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)

    if alert.is_acknowledged:
        return Response({
            'message': 'Alert already acknowledged',
            'acknowledged_by': alert.acknowledged_by.email if alert.acknowledged_by else None,
            'acknowledged_at': alert.acknowledged_at
        })

    alert.acknowledge(request.user)

    AdminAuditLog.log(
        admin=request.user,
        action='system.config_change',
        target_type='system_alert',
        target_id=str(alert.id),
        target_label=alert.title,
        details={'action': 'acknowledged'},
        request=request
    )

    return Response(SystemAlertSerializer(alert).data)


@api_view(['POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def system_alert_resolve(request, alert_id):
    """
    POST /v1/admin/alerts/system/<alert_id>/resolve/

    Resolve a system alert.
    """
    from apps.admin_api.models import SystemAlert
    from apps.admin_api.serializers import SystemAlertSerializer

    try:
        alert = SystemAlert.objects.get(id=alert_id)
    except SystemAlert.DoesNotExist:
        return Response({'error': 'Alert not found'}, status=status.HTTP_404_NOT_FOUND)

    if not alert.is_active:
        return Response({
            'message': 'Alert already resolved',
            'resolved_at': alert.resolved_at
        })

    alert.resolve()

    AdminAuditLog.log(
        admin=request.user,
        action='system.config_change',
        target_type='system_alert',
        target_id=str(alert.id),
        target_label=alert.title,
        details={'action': 'resolved'},
        request=request
    )

    return Response(SystemAlertSerializer(alert).data)


@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def alert_stats(request):
    """
    GET /v1/admin/alerts/stats/

    Get alert statistics for dashboard.
    """
    from apps.admin_api.models import AlertRule, SystemAlert, AlertNotification
    from django.db.models import Count

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    # System alert stats
    active_alerts = SystemAlert.objects.filter(is_active=True)
    active_count = active_alerts.count()
    critical_count = active_alerts.filter(level='critical').count()
    warning_count = active_alerts.filter(level__in=['warning', 'error']).count()

    # Notification stats
    alerts_today = AlertNotification.objects.filter(sent_at__gte=today_start).count()
    alerts_this_week = AlertNotification.objects.filter(sent_at__gte=week_ago).count()

    # Rule stats
    total_rules = AlertRule.objects.count()
    enabled_rules = AlertRule.objects.filter(is_enabled=True).count()

    # By type breakdown
    alerts_by_type = dict(
        AlertNotification.objects.filter(sent_at__gte=week_ago)
        .values('rule__alert_type')
        .annotate(count=Count('id'))
        .values_list('rule__alert_type', 'count')
    )

    # By severity breakdown
    alerts_by_severity = dict(
        AlertNotification.objects.filter(sent_at__gte=week_ago)
        .values('severity')
        .annotate(count=Count('id'))
        .values_list('severity', 'count')
    )

    return Response({
        'active_alerts': active_count,
        'critical_alerts': critical_count,
        'warning_alerts': warning_count,
        'alerts_today': alerts_today,
        'alerts_this_week': alerts_this_week,
        'enabled_rules': enabled_rules,
        'total_rules': total_rules,
        'by_type': alerts_by_type,
        'by_severity': alerts_by_severity
    })


# =====================
# Global Search Endpoint
# =====================

@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def admin_global_search(request):
    """
    Global search across all admin entities.
    
    GET /v1/admin/search/?q=<query>&type=<optional_type>
    
    Searches across:
    - Users (email, name)
    - Organizations (name, slug)
    - Chatbots (name)
    - Sites (domain, name)
    - Jobs (site domain)
    
    Query params:
        - q: Search query (required, min 2 characters)
        - type: Filter by type (users, organizations, chatbots, sites, jobs)
        - limit: Max results per category (default 5, max 20)
    """
    query = request.query_params.get('q', '').strip()
    search_type = request.query_params.get('type', 'all')
    limit = min(int(request.query_params.get('limit', 5)), 20)
    
    if len(query) < 2:
        return Response({
            'error': 'Search query must be at least 2 characters'
        }, status=400)
    
    results = {}
    
    # Search Users
    if search_type in ['all', 'users']:
        users = User.objects.filter(
            Q(email__icontains=query) |
            Q(name__icontains=query)
        ).order_by('-created_at')[:limit]
        results['users'] = [
            {
                'id': str(u.id),
                'type': 'user',
                'title': u.email,
                'subtitle': u.name or 'No name',
                'status': u.status,
                'url': f'/admin/users/{u.id}'
            }
            for u in users
        ]
    
    # Search Organizations
    if search_type in ['all', 'organizations']:
        orgs = Organization.objects.filter(
            Q(name__icontains=query) |
            Q(slug__icontains=query)
        ).order_by('-created_at')[:limit]
        results['organizations'] = [
            {
                'id': str(o.id),
                'type': 'organization',
                'title': o.name,
                'subtitle': o.slug,
                'status': o.status,
                'url': f'/admin/organizations/{o.id}'
            }
            for o in orgs
        ]
    
    # Search Chatbots
    if search_type in ['all', 'chatbots']:
        chatbots = Chatbot.objects.filter(
            Q(name__icontains=query)
        ).select_related().order_by('-created_at')[:limit]
        results['chatbots'] = [
            {
                'id': str(c.id),
                'type': 'chatbot',
                'title': c.name,
                'subtitle': f'Site: {c.site_id}',
                'status': c.status,
                'url': f'/admin/chatbots'
            }
            for c in chatbots
        ]
    
    # Search Sites
    if search_type in ['all', 'sites']:
        sites = Site.objects.filter(
            Q(domain__icontains=query) |
            Q(name__icontains=query)
        ).order_by('-created_at')[:limit]
        results['sites'] = [
            {
                'id': str(s.id),
                'type': 'site',
                'title': s.domain,
                'subtitle': s.name or '',
                'status': s.status,
                'url': f'/admin/sites'
            }
            for s in sites
        ]
    
    # Search Jobs (by site domain or ID)
    if search_type in ['all', 'jobs']:
        # Get site IDs matching the query
        matching_site_ids = Site.objects.filter(
            Q(domain__icontains=query)
        ).values_list('id', flat=True)[:20]
        
        jobs = IndexingJob.objects.filter(
            Q(site_id__in=matching_site_ids) |
            Q(url__icontains=query)
        ).order_by('-created_at')[:limit]
        
        results['jobs'] = [
            {
                'id': str(j.id),
                'type': 'job',
                'title': j.url or f'Job {str(j.id)[:8]}',
                'subtitle': f'Status: {j.status}',
                'status': j.status,
                'url': f'/admin/jobs'
            }
            for j in jobs
        ]
    
    # Calculate total count
    total_count = sum(len(v) for v in results.values())
    
    return Response({
        'query': query,
        'total_count': total_count,
        'results': results
    })


# =====================
# Announcement Endpoints
# =====================

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def announcements_list(request):
    """
    List all announcements or create a new one.
    
    GET /v1/admin/announcements/
    POST /v1/admin/announcements/
    """
    from apps.admin_api.models import Announcement
    from apps.admin_api.serializers import AnnouncementListSerializer, AnnouncementCreateSerializer
    
    if request.method == 'GET':
        # Get all announcements
        announcements = Announcement.objects.all().order_by('-created_at')
        
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter == 'active':
            announcements = announcements.filter(is_active=True)
        elif status_filter == 'inactive':
            announcements = announcements.filter(is_active=False)
        
        # Pagination
        limit = min(int(request.query_params.get('limit', 50)), 100)
        offset = int(request.query_params.get('offset', 0))
        total = announcements.count()
        announcements = announcements[offset:offset + limit]
        
        serializer = AnnouncementListSerializer(announcements, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'limit': limit,
            'offset': offset
        })
    
    elif request.method == 'POST':
        serializer = AnnouncementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create announcement
        announcement = Announcement.objects.create(
            created_by=request.user,
            **serializer.validated_data
        )
        
        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='announcement',
            target_id=str(announcement.id),
            target_label=announcement.title,
            request=request,
            details={'action': 'created'}
        )
        
        from apps.admin_api.serializers import AnnouncementDetailSerializer
        return Response(AnnouncementDetailSerializer(announcement).data, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
@throttle_classes([AdminRateThrottle])
def announcement_detail(request, announcement_id):
    """
    Get, update, or delete an announcement.
    
    GET/PUT/DELETE /v1/admin/announcements/<announcement_id>/
    """
    from apps.admin_api.models import Announcement
    from apps.admin_api.serializers import AnnouncementDetailSerializer, AnnouncementCreateSerializer
    
    announcement = get_object_or_404(Announcement, id=announcement_id)
    
    if request.method == 'GET':
        serializer = AnnouncementDetailSerializer(announcement)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = AnnouncementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Update fields
        for key, value in serializer.validated_data.items():
            setattr(announcement, key, value)
        announcement.save()
        
        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='announcement',
            target_id=str(announcement.id),
            target_label=announcement.title,
            request=request,
            details={'action': 'updated'}
        )
        
        return Response(AnnouncementDetailSerializer(announcement).data)
    
    elif request.method == 'DELETE':
        title = announcement.title
        announcement_id_str = str(announcement.id)
        announcement.delete()
        
        # Log the action
        AdminAuditLog.log(
            admin=request.user,
            action='system.config_change',
            target_type='announcement',
            target_id=announcement_id_str,
            target_label=title,
            request=request,
            details={'action': 'deleted'}
        )
        
        return Response({'status': 'deleted'}, status=204)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_active_announcements(request):
    """
    Get active announcements for the current user.
    Public endpoint - no auth required.
    
    GET /v1/announcements/active/
    """
    from apps.admin_api.models import Announcement
    
    tier = request.query_params.get('tier', 'basic')
    announcements = Announcement.get_active_announcements(tier=tier)
    
    # Return simplified data for frontend
    data = [
        {
            'id': str(a.id),
            'title': a.title,
            'message': a.message,
            'type': a.announcement_type,
            'style': a.style,
            'link_url': a.link_url,
            'link_text': a.link_text,
            'is_dismissible': a.is_dismissible,
        }
        for a in announcements[:5]  # Max 5 active announcements
    ]
    
    return Response(data)


@api_view(['POST'])
@permission_classes([AllowAny])
def dismiss_announcement(request, announcement_id):
    """
    Record that a user dismissed an announcement.
    
    POST /v1/announcements/<announcement_id>/dismiss/
    """
    from apps.admin_api.models import Announcement
    
    try:
        announcement = Announcement.objects.get(id=announcement_id)
        announcement.record_dismiss()
        return Response({'status': 'dismissed'})
    except Announcement.DoesNotExist:
        return Response({'error': 'Announcement not found'}, status=404)


# ==============================================================================
# FEATURE FLAGS VIEWS (PHASE 2)
# ==============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def feature_flag_list(request):
    """
    List and create feature flags.
    
    GET: List all feature flags
    POST: Create a new feature flag
    """
    from apps.admin_api.models import FeatureFlag, AdminAuditLog
    from apps.admin_api.serializers import FeatureFlagSerializer

    if request.method == 'GET':
        feature_flags = FeatureFlag.objects.all().order_by('-created_at')
        serializer = FeatureFlagSerializer(feature_flags, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = FeatureFlagSerializer(data=request.data)
        if serializer.is_valid():
            flag = serializer.save(created_by=request.user)
            
            # Log action
            AdminAuditLog.log_action(
                user=request.user,
                action="create_feature_flag",
                target_model="FeatureFlag",
                target_id=str(flag.id),
                details=f"Created feature flag: {flag.key}"
            )
            
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated, IsAdminUser])
def feature_flag_detail(request, pk):
    """
    Retrieve, update or delete a feature flag.
    """
    from apps.admin_api.models import FeatureFlag, AdminAuditLog
    from apps.admin_api.serializers import FeatureFlagSerializer

    try:
        flag = FeatureFlag.objects.get(pk=pk)
    except FeatureFlag.DoesNotExist:
        return Response({'error': 'Feature flag not found'}, status=404)

    if request.method == 'GET':
        serializer = FeatureFlagSerializer(flag)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = FeatureFlagSerializer(flag, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            
            # Log action
            AdminAuditLog.log_action(
                user=request.user,
                action="update_feature_flag",
                target_model="FeatureFlag",
                target_id=str(flag.id),
                details=f"Updated feature flag: {flag.key}"
            )
            
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        feature_key = flag.key
        flag.delete()
        
        # Log action
        AdminAuditLog.log_action(
            user=request.user,
            action="delete_feature_flag",
            target_model="FeatureFlag",
            target_id=str(pk),
            details=f"Deleted feature flag: {feature_key}"
        )
        
        return Response(status=204)


@api_view(['GET'])
@permission_classes([AllowAny])
def check_feature_flag(request):
    """
    Check if a feature flag is enabled for the current context.
    
    Query params:
    - key: The feature flag key (required)
    - distinct_id: Unique identifier for the user (optional, defaults to authenticated user ID or anon)
    """
    from apps.admin_api.models import FeatureFlag
    
    key = request.query_params.get('key')
    if not key:
        return Response({'error': 'Missing key parameter'}, status=400)

    # Context extraction
    user_id = None
    if request.user.is_authenticated:
        user_id = str(request.user.id)
    
    # Also check distinct_id param for anonymous users tracked by frontend
    distinct_id = request.query_params.get('distinct_id', user_id)
    
    # Determine user tier if logged in (simplified)
    # In a real app, you'd fetch the user's organization tier
    # For now, we'll assume 'basic' unless authenticated
    user_tier = 'basic'
    # TODO: Fetch actual tier from request.user -> Organization
        
    is_enabled = FeatureFlag.is_feature_enabled(
        key=key,
        user=request.user if request.user.is_authenticated else None,
        distinct_id=distinct_id
        # user_tier=user_tier 
    )
    
    return Response({'key': key, 'is_enabled': is_enabled})


# =====================
# Broadcast Email Endpoints
# =====================

@api_view(['POST'])
@permission_classes([IsSuperAdmin, AdminIPAllowlist])
@throttle_classes([AdminSensitiveOperationThrottle])
def broadcast_email(request):
    """
    Send a broadcast email to a segment of users.
    
    POST /v1/admin/broadcast-email/
    
    Request body:
        - subject: str (required)
        - body: str (required, can include HTML)
        - segment: str (required) - 'all', 'active', 'inactive', 'tier_basic', 'tier_premium', 'tier_enterprise'
        - send_test: bool (optional) - Send only to admin for testing
    """
    from django.core.mail import send_mass_mail, send_mail
    from apps.auth.models import User
    from apps.organizations.models import Membership
    
    subject = request.data.get('subject')
    body = request.data.get('body')
    segment = request.data.get('segment', 'all')
    send_test = request.data.get('send_test', False)
    
    if not subject or not body:
        return Response({
            'error': 'Subject and body are required'
        }, status=400)
    
    # Build recipient list based on segment
    if send_test:
        # Only send to the requesting admin
        recipients = [request.user.email]
    else:
        # Get users based on segment
        users = User.objects.filter(is_active=True, is_email_verified=True)
        
        if segment == 'active':
            # Active users (logged in within last 30 days)
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(days=30)
            users = users.filter(last_login__gte=cutoff)
        
        elif segment == 'inactive':
            # Inactive users (not logged in for 30+ days)
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(days=30)
            users = users.filter(last_login__lt=cutoff)
        
        elif segment.startswith('tier_'):
            # Filter by subscription tier
            tier = segment.replace('tier_', '')
            user_ids_with_tier = Membership.objects.filter(
                organization__subscription__plan=tier
            ).values_list('user_id', flat=True)
            users = users.filter(id__in=user_ids_with_tier)
        
        recipients = list(users.values_list('email', flat=True))
    
    if not recipients:
        return Response({
            'error': 'No recipients found for this segment',
            'segment': segment
        }, status=400)
    
    # Log the action BEFORE sending
    AdminAuditLog.log(
        admin=request.user,
        action='system.config_change',
        target_type='broadcast_email',
        target_id='',
        target_label=f'Broadcast: {subject[:50]}',
        request=request,
        details={
            'segment': segment,
            'recipient_count': len(recipients),
            'is_test': send_test,
            'subject': subject
        }
    )
    
    # Send emails
    try:
        from django.conf import settings
        from_email = settings.DEFAULT_FROM_EMAIL
        
        # For large lists, we should use async/background tasks
        # For now, send synchronously (consider Celery for production)
        success_count = 0
        fail_count = 0
        
        for recipient in recipients[:500]:  # Limit to 500 per batch
            try:
                send_mail(
                    subject=subject,
                    message=body,  # Plain text fallback
                    from_email=from_email,
                    recipient_list=[recipient],
                    html_message=body,
                    fail_silently=False
                )
                success_count += 1
            except Exception as e:
                fail_count += 1
                logger.error(f"Failed to send broadcast email to {recipient}: {e}")
        
        return Response({
            'status': 'success',
            'recipients_targeted': len(recipients),
            'sent': success_count,
            'failed': fail_count,
            'is_test': send_test,
            'segment': segment
        })
        
    except Exception as e:
        logger.error(f"Broadcast email failed: {e}")
        return Response({
            'error': f'Failed to send emails: {str(e)}'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAdminUser, AdminIPAllowlist])
def email_segments(request):
    """
    Get available email segments with counts.
    
    GET /v1/admin/broadcast-email/segments/
    """
    from apps.auth.models import User
    from apps.organizations.models import Membership
    from datetime import timedelta
    
    cutoff_30d = timezone.now() - timedelta(days=30)
    
    # Get base verified users
    verified_users = User.objects.filter(is_active=True, is_email_verified=True)
    
    # Get tier user IDs
    premium_ids = list(Membership.objects.filter(
        organization__subscription__plan='premium'
    ).values_list('user_id', flat=True))
    
    enterprise_ids = list(Membership.objects.filter(
        organization__subscription__plan='enterprise'
    ).values_list('user_id', flat=True))
    
    basic_ids = list(Membership.objects.filter(
        organization__subscription__plan='basic'
    ).values_list('user_id', flat=True))
    
    segments = [
        {
            'id': 'all',
            'name': 'All Verified Users',
            'count': verified_users.count(),
            'description': 'All users with verified emails'
        },
        {
            'id': 'active',
            'name': 'Active Users (30d)',
            'count': verified_users.filter(last_login__gte=cutoff_30d).count(),
            'description': 'Users who logged in within the last 30 days'
        },
        {
            'id': 'inactive',
            'name': 'Inactive Users (30d+)',
            'count': verified_users.filter(last_login__lt=cutoff_30d).count(),
            'description': 'Users who haven\'t logged in for 30+ days'
        },
        {
            'id': 'tier_basic',
            'name': 'Basic Tier',
            'count': verified_users.filter(id__in=basic_ids).count(),
            'description': 'Users on the free basic tier'
        },
        {
            'id': 'tier_premium',
            'name': 'Premium Tier',
            'count': verified_users.filter(id__in=premium_ids).count(),
            'description': 'Users on the premium tier'
        },
        {
            'id': 'tier_enterprise',
            'name': 'Enterprise Tier',
            'count': verified_users.filter(id__in=enterprise_ids).count(),
            'description': 'Users on the enterprise tier'
        },
    ]
    
    return Response({'segments': segments})
