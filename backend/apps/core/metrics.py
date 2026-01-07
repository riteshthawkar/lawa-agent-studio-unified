import time
import logging
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collect and store application metrics"""
    
    @staticmethod
    def increment_counter(metric_name, value=1, tags=None):
        """Increment a counter metric"""
        tags = tags or {}
        key = f"metrics:{metric_name}:{timezone.now().strftime('%Y-%m-%d-%H')}"
        
        # Store in cache for now (in production, use Redis or Prometheus)
        current_value = cache.get(key, 0)
        cache.set(key, current_value + value, timeout=3600)
        
        # Log metric
        logger.debug(
            "Counter metric updated",
            extra={'metric': metric_name, 'value': current_value + value, 'tags': tags}
        )
    
    @staticmethod
    def record_histogram(metric_name, value, tags=None):
        """Record a histogram metric"""
        tags = tags or {}
        key = f"histogram:{metric_name}:{timezone.now().strftime('%Y-%m-%d-%H')}"
        
        # Store in cache for now
        current_data = cache.get(key, {'count': 0, 'sum': 0, 'values': []})
        current_data['count'] += 1
        current_data['sum'] += value
        current_data['values'].append(value)
        
        # Keep only last 1000 values
        if len(current_data['values']) > 1000:
            current_data['values'] = current_data['values'][-1000:]
        
        cache.set(key, current_data, timeout=3600)
        
        # Log metric
        logger.debug(
            "Histogram metric recorded",
            extra={'metric': metric_name, 'value': value, 'tags': tags}
        )
    
    @staticmethod
    def get_metrics():
        """Get current metrics"""
        metrics = {}
        
        # Get counter metrics
        for key in cache.keys("metrics:*"):
            if key.startswith("metrics:"):
                value = cache.get(key, 0)
                metric_name = key.split(":")[1]
                metrics[metric_name] = value
        
        # Get histogram metrics
        for key in cache.keys("histogram:*"):
            if key.startswith("histogram:"):
                data = cache.get(key, {})
                metric_name = key.split(":")[1]
                if data.get('count', 0) > 0:
                    metrics[f"{metric_name}_count"] = data['count']
                    metrics[f"{metric_name}_sum"] = data['sum']
                    metrics[f"{metric_name}_avg"] = data['sum'] / data['count']
        
        return metrics


class DatabaseMetrics:
    """Database performance metrics"""
    
    @staticmethod
    def get_connection_count():
        """Get number of active database connections"""
        return len(connection.queries)
    
    @staticmethod
    def get_query_count():
        """Get number of queries executed"""
        return len(connection.queries)
    
    @staticmethod
    def get_slow_queries(threshold_ms=100):
        """Get queries slower than threshold"""
        slow_queries = []
        for query in connection.queries:
            if query['time'] and float(query['time']) > threshold_ms:
                slow_queries.append({
                    'sql': query['sql'][:200] + '...' if len(query['sql']) > 200 else query['sql'],
                    'time': query['time']
                })
        return slow_queries


class HealthChecker:
    """System health checks"""
    
    @staticmethod
    def check_database():
        """Check database connectivity"""
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False
    
    @staticmethod
    def check_redis():
        """Check Redis connectivity (if enabled)"""
        if not settings.USE_REDIS:
            return True
        
        try:
            import redis
            r = redis.from_url(settings.REDIS_URL)
            r.ping()
            return True
        except Exception:
            return False
    
    @staticmethod
    def check_external_services():
        """Check external service connectivity"""
        services = {
            'indexing_service': settings.INDEXING_API_BASE,
            'chatbot_service': settings.CHATBOT_API_BASE,
        }
        
        results = {}
        for service_name, base_url in services.items():
            try:
                import requests
                response = requests.get(f"{base_url}/health", timeout=5)
                results[service_name] = response.status_code == 200
            except Exception:
                results[service_name] = False
        
        return results
    
    @staticmethod
    def get_health_status():
        """Get overall health status"""
        return {
            'database': HealthChecker.check_database(),
            'redis': HealthChecker.check_redis(),
            'external_services': HealthChecker.check_external_services(),
            'timestamp': timezone.now().isoformat()
        }
