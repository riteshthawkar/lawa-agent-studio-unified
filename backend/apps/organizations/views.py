from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Organization, Membership
from .serializers import (
    OrganizationSerializer,
    OrganizationCreateSerializer,
    OrganizationDetailSerializer,
    MembershipSerializer
)
from apps.core.views import BaseViewSet


class OrganizationViewSet(BaseViewSet):
    """Organization management"""
    queryset = Organization.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return OrganizationCreateSerializer
        elif self.action == 'retrieve':
            return OrganizationDetailSerializer
        return OrganizationSerializer

    def get_queryset(self):
        """Filter organizations by user membership - optimized to prevent N+1 queries"""
        user = self.request.user
        return Organization.objects.filter(
            memberships__user=user
        ).prefetch_related(
            'memberships',  # Prefetch all memberships
            'memberships__user'  # And their users
        ).distinct()

    def create(self, request, *args, **kwargs):
        """Create new organization and add user as owner"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = serializer.save()
        
        # Add current user as owner
        Membership.objects.create(
            user=request.user,
            organization=organization,
            role='owner'
        )
        
        return Response(
            OrganizationDetailSerializer(organization).data,
            status=status.HTTP_201_CREATED
        )


class MembershipViewSet(BaseViewSet):
    """Membership management"""
    queryset = Membership.objects.all()
    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter memberships by organization"""
        org_id = self.kwargs.get('org_id')
        if org_id:
            return Membership.objects.filter(organization_id=org_id)
        return Membership.objects.none()

    def create(self, request, *args, **kwargs):
        """Add user to organization"""
        org_id = self.kwargs.get('org_id')
        if not org_id:
            return Response(
                {'error': 'Organization ID required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if user has permission to add members
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
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Add organization context
        serializer.validated_data['organization_id'] = org_id
        membership = serializer.save()
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_organizations(request):
    """Get user's organizations"""
    memberships = Membership.objects.filter(user=request.user).select_related('organization')
    organizations = [membership.organization for membership in memberships]
    
    serializer = OrganizationSerializer(organizations, many=True)
    return Response(serializer.data)
