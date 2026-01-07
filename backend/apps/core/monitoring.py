from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .metrics import MetricsCollector, DatabaseMetrics, HealthChecker


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """Health check endpoint"""
    health_status = HealthChecker.get_health_status()
    
    # Determine overall health
    all_healthy = all([
        health_status['database'],
        health_status['redis'],
        all(health_status['external_services'].values())
    ])
    
    return Response({
        'status': 'healthy' if all_healthy else 'unhealthy',
        'checks': health_status
    }, status=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def metrics(request):
    """Get application metrics"""
    metrics_data = MetricsCollector.get_metrics()
    
    # Add database metrics
    metrics_data.update({
        'db_connection_count': DatabaseMetrics.get_connection_count(),
        'db_query_count': DatabaseMetrics.get_query_count(),
        'db_slow_queries': len(DatabaseMetrics.get_slow_queries())
    })
    
    return Response(metrics_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def system_info(request):
    """Get system information"""
    import sys
    import platform
    from django import get_version
    
    return Response({
        'python_version': sys.version,
        'django_version': get_version(),
        'platform': platform.platform(),
        'timezone': str(timezone.get_current_timezone()),
        'debug': settings.DEBUG,
        'database_engine': settings.DATABASES['default']['ENGINE'],
        'use_redis': settings.USE_REDIS,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_metric(request):
    """Record a custom metric"""
    metric_name = request.data.get('name')
    metric_value = request.data.get('value', 1)
    metric_type = request.data.get('type', 'counter')
    tags = request.data.get('tags', {})
    
    if not metric_name:
        return Response(
            {'error': 'Metric name is required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if metric_type == 'counter':
        MetricsCollector.increment_counter(metric_name, metric_value, tags)
    elif metric_type == 'histogram':
        MetricsCollector.record_histogram(metric_name, metric_value, tags)
    else:
        return Response(
            {'error': 'Invalid metric type'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    return Response({'status': 'recorded'})
