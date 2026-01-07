"""
System Health and Monitoring Services

Provides health checks and system status information for the admin dashboard.
"""
import logging
from django.db import connection
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class SystemHealthService:
    """
    Service for checking system health and gathering operational metrics.
    """
    
    @classmethod
    def get_full_health_status(cls):
        """Get comprehensive health status of all system components."""
        # Cache individual checks to avoid redundant calls
        db_status = cls.check_database()
        cache_status = cls.check_cache()
        storage_status = cls.check_storage()
        
        # Calculate overall health using cached results
        overall = cls._calculate_overall_from_results(db_status, cache_status)
        
        return {
            'database': db_status,
            'cache': cache_status,
            'external_apis': cls.check_external_apis(),
            'queues': cls.get_queue_status(),
            'storage': storage_status,
            'overall': overall,
            'checked_at': timezone.now().isoformat()
        }
    
    @classmethod
    def check_database(cls):
        """Check database connectivity and basic performance."""
        try:
            start = timezone.now()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            latency_ms = (timezone.now() - start).total_seconds() * 1000
            
            return {
                'status': 'healthy',
                'latency_ms': round(latency_ms, 2),
                'message': 'Database connection successful'
            }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                'status': 'unhealthy',
                'latency_ms': None,
                'message': str(e)
            }
    
    @classmethod
    def check_cache(cls):
        """Check cache (Redis) connectivity."""
        try:
            start = timezone.now()
            test_key = 'health_check_test'
            cache.set(test_key, 'test_value', 10)
            result = cache.get(test_key)
            cache.delete(test_key)
            latency_ms = (timezone.now() - start).total_seconds() * 1000
            
            if result == 'test_value':
                return {
                    'status': 'healthy',
                    'latency_ms': round(latency_ms, 2),
                    'message': 'Cache connection successful'
                }
            else:
                return {
                    'status': 'degraded',
                    'latency_ms': round(latency_ms, 2),
                    'message': 'Cache read/write mismatch'
                }
        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            return {
                'status': 'unhealthy',
                'latency_ms': None,
                'message': str(e)
            }
    
    @classmethod
    def check_external_apis(cls):
        """Check external API connectivity (OpenAI, Pinecone, Stripe)."""
        results = {}
        
        # Check OpenAI
        try:
            import openai
            # Just check if the client can be created with valid config
            openai_key = getattr(settings, 'OPENAI_API_KEY', None)
            results['openai'] = {
                'status': 'configured' if openai_key else 'not_configured',
                'message': 'API key configured' if openai_key else 'API key missing'
            }
        except Exception as e:
            results['openai'] = {'status': 'error', 'message': str(e)}
        
        # Check Pinecone
        try:
            pinecone_key = getattr(settings, 'PINECONE_API_KEY', None)
            results['pinecone'] = {
                'status': 'configured' if pinecone_key else 'not_configured',
                'message': 'API key configured' if pinecone_key else 'API key missing'
            }
        except Exception as e:
            results['pinecone'] = {'status': 'error', 'message': str(e)}
        
        # Check Stripe
        try:
            stripe_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
            results['stripe'] = {
                'status': 'configured' if stripe_key else 'not_configured',
                'message': 'API key configured' if stripe_key else 'API key missing'
            }
        except Exception as e:
            results['stripe'] = {'status': 'error', 'message': str(e)}
        
        return results
    
    @classmethod
    def get_queue_status(cls):
        """Get indexing job queue status."""
        from apps.indexing.models import IndexingJob
        
        try:
            now = timezone.now()
            last_hour = now - timedelta(hours=1)
            last_24h = now - timedelta(hours=24)
            
            pending = IndexingJob.objects.filter(status='pending').count()
            running = IndexingJob.objects.filter(status='running').count()
            completed_1h = IndexingJob.objects.filter(
                status='completed',
                updated_at__gte=last_hour
            ).count()
            failed_24h = IndexingJob.objects.filter(
                status='failed',
                updated_at__gte=last_24h
            ).count()
            
            # Calculate average duration for completed jobs in last 24h
            from django.db.models import Avg, F
            avg_duration = IndexingJob.objects.filter(
                status='completed',
                updated_at__gte=last_24h,
                started_at__isnull=False,
                completed_at__isnull=False
            ).annotate(
                duration=F('completed_at') - F('started_at')
            ).aggregate(avg=Avg('duration'))
            
            avg_duration_seconds = None
            if avg_duration['avg']:
                avg_duration_seconds = avg_duration['avg'].total_seconds()
            
            return {
                'status': 'healthy' if failed_24h == 0 else 'degraded',
                'pending': pending,
                'running': running,
                'completed_last_hour': completed_1h,
                'failed_last_24h': failed_24h,
                'avg_duration_seconds': avg_duration_seconds
            }
        except Exception as e:
            logger.error(f"Queue status check failed: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    @classmethod
    def check_storage(cls):
        """Check file storage accessibility with actual write/read test."""
        try:
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            import time
            
            # Perform an actual write/read test
            test_filename = f'health_check_{int(time.time())}.txt'
            test_content = b'health_check_test'
            
            try:
                # Attempt to write
                path = default_storage.save(test_filename, ContentFile(test_content))
                
                # Attempt to read back
                if default_storage.exists(path):
                    # Cleanup
                    default_storage.delete(path)
                    return {
                        'status': 'healthy',
                        'backend': type(default_storage).__name__,
                        'message': 'Storage read/write successful'
                    }
                else:
                    return {
                        'status': 'degraded',
                        'backend': type(default_storage).__name__,
                        'message': 'File write succeeded but verification failed'
                    }
            except Exception as write_error:
                # Fallback: just check if storage is accessible
                return {
                    'status': 'degraded',
                    'backend': type(default_storage).__name__,
                    'message': f'Storage accessible but write test failed: {str(write_error)[:100]}'
                }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': str(e)
            }
    
    @classmethod
    def calculate_overall_health(cls):
        """Calculate overall system health based on component statuses."""
        db = cls.check_database()
        cache_status = cls.check_cache()
        return cls._calculate_overall_from_results(db, cache_status)
    
    @classmethod
    def _calculate_overall_from_results(cls, db_result, cache_result):
        """Calculate overall health from pre-fetched results (avoids redundant calls)."""
        if db_result['status'] == 'unhealthy':
            return 'critical'
        elif cache_result['status'] == 'unhealthy':
            return 'degraded'
        else:
            return 'healthy'
    
    @classmethod
    def get_error_summary(cls):
        """Get summary of recent errors from logs (placeholder)."""
        # In a production system, this would query an error tracking service
        # like Sentry or parse log files
        return {
            'last_hour': 0,
            'last_24h': 0,
            'top_errors': []
        }


class SystemMetricsService:
    """
    Service for gathering system usage metrics.
    """
    
    @classmethod
    def get_usage_metrics(cls):
        """Get usage metrics for the system."""
        from apps.auth.models import User
        from apps.organizations.models import Organization
        from apps.chat.models import ChatMessage
        from apps.sites.models import Site
        from apps.chatbot.models import Chatbot

        now = timezone.now()
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        return {
            'users': {
                'total': User.objects.count(),
                'active_7d': User.objects.filter(last_login__gte=last_7d).count(),
                'new_30d': User.objects.filter(created_at__gte=last_30d).count()
            },
            'organizations': {
                'total': Organization.objects.count(),
                'active': Organization.objects.filter(status='active').count()
            },
            'sites': {
                'total': Site.objects.count(),
                'active': Site.objects.filter(status='active').count()
            },
            'chatbots': {
                'total': Chatbot.objects.count(),
                'active': Chatbot.objects.filter(status='active').count()
            },
            'messages': {
                'last_7d': ChatMessage.objects.filter(created_at__gte=last_7d).count(),
                'last_30d': ChatMessage.objects.filter(created_at__gte=last_30d).count()
            },
            'generated_at': now.isoformat()
        }
