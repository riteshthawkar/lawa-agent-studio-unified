"""
Caching Module for LAWA Platform
Provides comprehensive caching strategies for improved performance.
"""

import json
import logging
from typing import Any, Optional, Dict, List
from django.core.cache import cache
from django.conf import settings
from django.core.cache.utils import make_template_fragment_key
from django.utils.encoding import force_str
import hashlib
import time

logger = logging.getLogger(__name__)

class CacheManager:
    """Centralized cache management for the LAWA platform."""
    
    # Cache key prefixes for different data types
    CACHE_PREFIXES = {
        'user': 'user',
        'site': 'site',
        'chatbot': 'chatbot',
        'indexing_job': 'indexing_job',
        'dashboard_stats': 'dashboard_stats',
        'api_response': 'api_response',
        'health_check': 'health_check',
    }
    
    # Default cache timeouts (in seconds)
    CACHE_TIMEOUTS = {
        'user': 3600,           # 1 hour
        'site': 1800,           # 30 minutes
        'chatbot': 1800,        # 30 minutes
        'indexing_job': 300,    # 5 minutes
        'dashboard_stats': 600, # 10 minutes
        'api_response': 300,    # 5 minutes
        'health_check': 60,     # 1 minute
    }
    
    @classmethod
    def _make_cache_key(cls, prefix: str, identifier: str, suffix: str = '') -> str:
        """Generate a standardized cache key."""
        key_parts = [cls.CACHE_PREFIXES.get(prefix, prefix), str(identifier)]
        if suffix:
            key_parts.append(suffix)
        return ':'.join(key_parts)
    
    @classmethod
    def get(cls, prefix: str, identifier: str, suffix: str = '') -> Optional[Any]:
        """Get data from cache."""
        cache_key = cls._make_cache_key(prefix, identifier, suffix)
        try:
            data = cache.get(cache_key)
            if data is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return data
            else:
                logger.debug(f"Cache MISS: {cache_key}")
                return None
        except Exception as e:
            logger.error(f"Cache GET error for {cache_key}: {e}")
            return None
    
    @classmethod
    def set(cls, prefix: str, identifier: str, data: Any, timeout: Optional[int] = None, suffix: str = '') -> bool:
        """Set data in cache."""
        cache_key = cls._make_cache_key(prefix, identifier, suffix)
        timeout = timeout or cls.CACHE_TIMEOUTS.get(prefix, 300)
        
        try:
            cache.set(cache_key, data, timeout)
            logger.debug(f"Cache SET: {cache_key} (timeout: {timeout}s)")
            return True
        except Exception as e:
            logger.error(f"Cache SET error for {cache_key}: {e}")
            return False
    
    @classmethod
    def delete(cls, prefix: str, identifier: str, suffix: str = '') -> bool:
        """Delete data from cache."""
        cache_key = cls._make_cache_key(prefix, identifier, suffix)
        try:
            cache.delete(cache_key)
            logger.debug(f"Cache DELETE: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Cache DELETE error for {cache_key}: {e}")
            return False
    
    @classmethod
    def delete_pattern(cls, pattern: str) -> int:
        """Delete all cache keys matching a pattern."""
        try:
            # This is a simplified implementation
            # In production, you might want to use Redis SCAN for better performance
            return cache.delete_many(cache.keys(pattern))
        except Exception as e:
            logger.error(f"Cache DELETE_PATTERN error for {pattern}: {e}")
            return 0
    
    @classmethod
    def get_or_set(cls, prefix: str, identifier: str, callable_func, timeout: Optional[int] = None, suffix: str = '') -> Any:
        """Get data from cache or set it using a callable function."""
        data = cls.get(prefix, identifier, suffix)
        if data is not None:
            return data
        
        # Data not in cache, call the function to get it
        try:
            data = callable_func()
            cls.set(prefix, identifier, data, timeout, suffix)
            return data
        except Exception as e:
            logger.error(f"Cache GET_OR_SET error for {prefix}:{identifier}: {e}")
            raise e

class ModelCacheMixin:
    """Mixin for Django models to add caching capabilities."""
    
    def get_cache_key(self, suffix: str = '') -> str:
        """Generate cache key for this model instance."""
        return CacheManager._make_cache_key(
            self.__class__.__name__.lower(),
            str(self.pk),
            suffix
        )
    
    def cache_set(self, data: Any, timeout: Optional[int] = None, suffix: str = '') -> bool:
        """Cache data for this model instance."""
        return CacheManager.set(
            self.__class__.__name__.lower(),
            str(self.pk),
            data,
            timeout,
            suffix
        )
    
    def cache_get(self, suffix: str = '') -> Optional[Any]:
        """Get cached data for this model instance."""
        return CacheManager.get(
            self.__class__.__name__.lower(),
            str(self.pk),
            suffix
        )
    
    def cache_delete(self, suffix: str = '') -> bool:
        """Delete cached data for this model instance."""
        return CacheManager.delete(
            self.__class__.__name__.lower(),
            str(self.pk),
            suffix
        )

class APICacheMixin:
    """Mixin for API views to add caching capabilities."""
    
    @classmethod
    def get_api_cache_key(cls, request, view_name: str = '') -> str:
        """Generate cache key for API response."""
        # Create a hash of the request parameters
        cache_data = {
            'path': request.path,
            'method': request.method,
            'query_params': dict(request.GET),
            'user_id': getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
            'org_id': getattr(request, 'org_id', None),
        }
        
        cache_string = json.dumps(cache_data, sort_keys=True)
        cache_hash = hashlib.md5(cache_string.encode()).hexdigest()
        
        return CacheManager._make_cache_key('api_response', f"{view_name}:{cache_hash}")
    
    @classmethod
    def cache_api_response(cls, request, response_data: Any, timeout: int = 300, view_name: str = '') -> bool:
        """Cache API response."""
        cache_key = cls.get_api_cache_key(request, view_name)
        return CacheManager.set('api_response', cache_key, response_data, timeout)
    
    @classmethod
    def get_cached_api_response(cls, request, view_name: str = '') -> Optional[Any]:
        """Get cached API response."""
        cache_key = cls.get_api_cache_key(request, view_name)
        return CacheManager.get('api_response', cache_key)

class QueryCacheMixin:
    """Mixin for database queries to add caching capabilities."""
    
    @classmethod
    def get_query_cache_key(cls, query_hash: str, model_name: str = '') -> str:
        """Generate cache key for database query."""
        return CacheManager._make_cache_key('query', f"{model_name}:{query_hash}")
    
    @classmethod
    def cache_query_result(cls, query_hash: str, result: Any, timeout: int = 300, model_name: str = '') -> bool:
        """Cache database query result."""
        return CacheManager.set('query', f"{model_name}:{query_hash}", result, timeout)
    
    @classmethod
    def get_cached_query_result(cls, query_hash: str, model_name: str = '') -> Optional[Any]:
        """Get cached database query result."""
        return CacheManager.get('query', f"{model_name}:{query_hash}")

# Decorators for easy caching
def cache_result(prefix: str, timeout: Optional[int] = None, suffix: str = ''):
    """Decorator to cache function results."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
            return CacheManager.get_or_set(
                prefix, 
                cache_key, 
                lambda: func(*args, **kwargs), 
                timeout, 
                suffix
            )
        return wrapper
    return decorator

def cache_invalidate(prefix: str, identifier: str, suffix: str = ''):
    """Decorator to invalidate cache after function execution."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            CacheManager.delete(prefix, identifier, suffix)
            return result
        return wrapper
    return decorator

# Cache warming functions
def warm_dashboard_cache():
    """Warm up dashboard-related caches."""
    try:
        from apps.frontend.views import get_dashboard_stats
        # This would be called during application startup
        logger.info("Warming dashboard cache...")
        # Implementation would depend on the actual dashboard stats function
    except Exception as e:
        logger.error(f"Error warming dashboard cache: {e}")

def warm_site_cache(site_id: str):
    """Warm up site-related caches."""
    try:
        from apps.sites.models import Site
        site = Site.objects.get(id=site_id)
        # Cache site data
        CacheManager.set('site', site_id, {
            'id': str(site.id),
            'domain': site.domain,
            'status': site.status,
            'last_indexed_at': site.last_indexed_at.isoformat() if site.last_indexed_at else None,
        })
        logger.info(f"Warmed cache for site {site_id}")
    except Exception as e:
        logger.error(f"Error warming site cache for {site_id}: {e}")

# Cache statistics and monitoring
class CacheStats:
    """Cache statistics and monitoring."""
    
    @classmethod
    def get_cache_info(cls) -> Dict[str, Any]:
        """Get cache information and statistics."""
        try:
            return {
                'cache_backend': settings.CACHES['default']['BACKEND'],
                'cache_location': settings.CACHES['default'].get('LOCATION', 'N/A'),
                'cache_options': settings.CACHES['default'].get('OPTIONS', {}),
                'cache_timeout': settings.CACHES['default'].get('TIMEOUT', 300),
            }
        except Exception as e:
            logger.error(f"Error getting cache info: {e}")
            return {'error': str(e)}
    
    @classmethod
    def clear_all_cache(cls) -> bool:
        """Clear all cache data."""
        try:
            cache.clear()
            logger.info("All cache data cleared")
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
