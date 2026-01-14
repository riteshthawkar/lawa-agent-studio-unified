from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status


class BaseViewSet(viewsets.ModelViewSet):
    """Base viewset with common functionality"""
    
    def get_queryset(self):
        """Filter queryset by organization if applicable"""
        queryset = super().get_queryset()
        request = self.request
        
        # Add organization filtering if the model has org_id field
        if hasattr(queryset.model, 'org_id') and hasattr(request, 'org_id'):
            return queryset.filter(org_id=request.org_id)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def health(self, request):
        """Health check endpoint"""
        return Response({'status': 'healthy'}, status=status.HTTP_200_OK)
