from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import UsageEvent, Quota, UpgradeInterest
from .serializers import (
    QuotaSerializer,
    UpgradeInterestCreateSerializer,
    UpgradeInterestSerializer,
    UsageSummarySerializer
)
from .services import QuotaService
from apps.core.views import BaseViewSet


class UsageViewSet(BaseViewSet):
    """Usage tracking"""
    queryset = UsageEvent.objects.all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter usage events by organization"""
        queryset = super().get_queryset()
        request = self.request
        
        if hasattr(request, 'org_id') and request.org_id:
            return queryset.filter(org_id=request.org_id)
        
        return queryset.none()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def organization_usage(request, org_id):
    """Get organization usage for current period"""
    # Check organization access
    if hasattr(request, 'org_id') and str(org_id) != str(request.org_id):
        return Response(
            {'error': 'Organization access denied'}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get current period (current month)
    current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Aggregate usage by type
    usage_data = UsageEvent.objects.filter(
        org_id=org_id,
        occurred_at__gte=current_month
    ).values('type').annotate(
        total_units=Sum('units'),
        total_cost=Sum('cost_cents')
    )
    
    # Format response
    usage = {
        'embeddings': 0,
        'queries': 0,
        'index_writes': 0,
        'chat_messages': 0,
        'total_cost_cents': 0
    }
    
    for item in usage_data:
        usage[item['type']] = item['total_units'] or 0
        usage['total_cost_cents'] += item['total_cost'] or 0
    
    return Response({
        'period': 'current',
        'period_start': current_month,
        'usage': usage
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def organization_quotas(request, org_id):
    """Get organization quotas"""
    # Check organization access
    if hasattr(request, 'org_id') and str(org_id) != str(request.org_id):
        return Response(
            {'error': 'Organization access denied'}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        quota = Quota.objects.filter(org_id=org_id).latest('created_at')
        return Response(QuotaSerializer(quota).data)
    except Quota.DoesNotExist:
        # Return default quotas
        return Response({
            'limits': {
                'max_pages': 1000,
                'max_vectors': 10000,
                'monthly_cost_cap': 10000,
                'concurrent_jobs': 3
            },
            'usage': {
                'pages': 0,
                'vectors': 0,
                'cost_cents': 0,
                'active_jobs': 0
            },
            'period_start': timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            'period_end': timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timezone.timedelta(days=30)
        })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_quota(request, org_id):
    """Create or update organization quota"""
    # Check organization access
    if hasattr(request, 'org_id') and str(org_id) != str(request.org_id):
        return Response(
            {'error': 'Organization access denied'}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Check if user has admin/owner role
    from apps.organizations.models import Membership
    try:
        membership = Membership.objects.get(
            user=request.user,
            organization_id=org_id,
            role__in=['owner', 'admin']
        )
    except Membership.DoesNotExist:
        return Response(
            {'error': 'Insufficient permissions'}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    serializer = QuotaSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Create quota
    quota = serializer.save(org_id=org_id)

    return Response(QuotaSerializer(quota).data, status=status.HTTP_201_CREATED)


class UsageSummaryView(APIView):
    """
    Get usage summary for the current organization.
    Returns current usage vs limits for display in dashboard.
    """
    permission_classes = [IsAuthenticated]


    def _get_organization(self, request):
        """Helper to get organization from request or user context"""
        # 1. Try request.org (set by specific middleware)
        org = getattr(request, 'org', None)
        if org:
            return org
            
        # 2. Try request.org_id (set by core middleware)
        if getattr(request, 'org_id', None):
            from apps.organizations.models import Organization
            try:
                return Organization.objects.get(id=request.org_id)
            except Organization.DoesNotExist:
                pass
                
        # 3. Fallback to user's first organization
        if request.user.is_authenticated:
            from apps.organizations.models import Membership
            membership = Membership.objects.filter(user=request.user).order_by('created_at').first()
            if membership:
                return membership.organization
                
        return None

    @extend_schema(
        summary="Get usage summary",
        description="Returns usage statistics and limits for the organization",
        responses={200: UsageSummarySerializer},
        tags=['Usage']
    )
    def get(self, request):
        """Get usage summary"""
        org = self._get_organization(request)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)

        summary = QuotaService.get_usage_summary(org.id)
        return Response(summary)


class JoinWaitlistView(APIView):
    """
    Join the waitlist for a paid plan.
    Used to track user interest before Stripe is configured.
    """
    permission_classes = [IsAuthenticated]

    def _get_organization(self, request):
        """Helper to get organization from request or user context"""
        # 1. Try request.org (set by specific middleware)
        org = getattr(request, 'org', None)
        if org:
            return org
            
        # 2. Try request.org_id (set by core middleware)
        if getattr(request, 'org_id', None):
            from apps.organizations.models import Organization
            try:
                return Organization.objects.get(id=request.org_id)
            except Organization.DoesNotExist:
                pass
                
        # 3. Fallback to user's first organization
        if request.user.is_authenticated:
            from apps.organizations.models import Membership
            membership = Membership.objects.filter(user=request.user).order_by('created_at').first()
            if membership:
                return membership.organization
                
        return None

    @extend_schema(
        summary="Join upgrade waitlist",
        description="Express interest in upgrading to a paid plan",
        request=UpgradeInterestCreateSerializer,
        responses={
            201: UpgradeInterestSerializer,
            400: OpenApiResponse(description="Invalid request"),
        },
        tags=['Usage']
    )
    def post(self, request):
        """Join the waitlist for a plan upgrade"""
        org = self._get_organization(request)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context. Please ensure you belong to an organization.',
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = UpgradeInterestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Check if already on waitlist for this plan
        existing = UpgradeInterest.objects.filter(
            organization=org,
            user=request.user,
            interested_plan=serializer.validated_data['interested_plan'],
            status='pending'
        ).first()

        if existing:
            return Response({
                'message': 'You are already on the waitlist for this plan',
                'interest': UpgradeInterestSerializer(existing).data
            }, status=status.HTTP_200_OK)

        # Get current usage for metadata
        usage_summary = QuotaService.get_usage_summary(org.id)

        # Create the interest record
        interest = UpgradeInterest.objects.create(
            organization=org,
            user=request.user,
            interested_plan=serializer.validated_data['interested_plan'],
            email=serializer.validated_data['email'],
            source=serializer.validated_data.get('source', 'billing_page'),
            company_name=serializer.validated_data.get('company_name', ''),
            message=serializer.validated_data.get('message', ''),
            metadata={
                'current_plan': org.plan_tier,
                'usage_at_signup': usage_summary,
            }
        )

        return Response({
            'message': 'Successfully joined the waitlist! We will notify you when the plan is available.',
            'interest': UpgradeInterestSerializer(interest).data
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Check waitlist status",
        description="Check if user is on the waitlist",
        responses={200: UpgradeInterestSerializer(many=True)},
        tags=['Usage']
    )
    def get(self, request):
        """Get user's waitlist entries"""
        org = self._get_organization(request)
        if not org:
            return Response({
                'error': 'no_organization',
                'message': 'No organization context',
            }, status=status.HTTP_400_BAD_REQUEST)

        interests = UpgradeInterest.objects.filter(
            organization=org,
            user=request.user
        ).order_by('-created_at')

        return Response({
            'interests': UpgradeInterestSerializer(interests, many=True).data
        })
