"""
Health Check Views for LAWA Platform
Provides health monitoring endpoints for all services.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from .health_checks import get_health_status
import asyncio
import logging

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Basic health check endpoint.
    Returns 200 if service is running.
    """
    return Response({
        "status": "healthy",
        "service": "lawa-django-backend",
        "timestamp": "2025-09-28T00:00:00Z"
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([AllowAny])
def health_detailed(request):
    """
    Detailed health check endpoint.
    Returns comprehensive health status of all services.
    """
    try:
        # Run async health checks
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        health_data = loop.run_until_complete(get_health_status())
        loop.close()
        
        # Determine HTTP status code based on health status
        if health_data["status"] == "healthy":
            http_status = status.HTTP_200_OK
        elif health_data["status"] == "degraded":
            http_status = status.HTTP_200_OK  # Still operational
        else:
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        
        return Response(health_data, status=http_status)
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return Response({
            "status": "unhealthy",
            "error": str(e),
            "service": "lawa-django-backend"
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

@api_view(['GET'])
@permission_classes([AllowAny])
def health_ready(request):
    """
    Readiness probe for Kubernetes.
    Returns 200 if service is ready to accept traffic.
    """
    try:
        # Check critical dependencies
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        
        return Response({
            "status": "ready",
            "service": "lawa-django-backend"
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return Response({
            "status": "not_ready",
            "error": str(e),
            "service": "lawa-django-backend"
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

@api_view(['GET'])
@permission_classes([AllowAny])
def health_live(request):
    """
    Liveness probe for Kubernetes.
    Returns 200 if service is alive (not deadlocked).
    """
    return Response({
        "status": "alive",
        "service": "lawa-django-backend"
    }, status=status.HTTP_200_OK)
