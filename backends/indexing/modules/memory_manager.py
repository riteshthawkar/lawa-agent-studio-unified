"""
Memory management utilities for indexing service.

Provides functions to monitor and manage memory usage, prevent leaks,
and clean up old data to keep memory usage under control.
"""

import gc
import logging
import psutil
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manager for monitoring and controlling memory usage"""

    # Configuration
    MAX_CORPUS_SIZE = 10000  # Maximum documents to keep in memory
    MAX_CACHE_AGE_HOURS = 24  # Maximum age for cached data
    MEMORY_WARNING_THRESHOLD = 0.8  # 80% memory usage threshold
    MEMORY_CRITICAL_THRESHOLD = 0.9  # 90% memory usage threshold

    def __init__(self):
        """Initialize memory manager"""
        self.corpus_cache = deque(maxlen=self.MAX_CORPUS_SIZE)
        self.model_cache = {}
        self.last_cleanup = datetime.now()
        self.memory_warnings = []

    def check_memory_usage(self) -> Dict[str, any]:
        """
        Check current memory usage and return statistics.

        Returns:
            dict: Memory usage statistics
        """
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()

            # Get system memory
            system_memory = psutil.virtual_memory()

            stats = {
                'process_memory_mb': memory_info.rss / 1024 / 1024,
                'process_memory_percent': memory_percent,
                'system_memory_percent': system_memory.percent,
                'system_memory_available_mb': system_memory.available / 1024 / 1024,
                'threshold_warning': self.MEMORY_WARNING_THRESHOLD * 100,
                'threshold_critical': self.MEMORY_CRITICAL_THRESHOLD * 100,
                'status': 'normal'
            }

            # Determine status
            if memory_percent / 100 >= self.MEMORY_CRITICAL_THRESHOLD:
                stats['status'] = 'critical'
                logger.error(
                    f"CRITICAL: Memory usage at {memory_percent:.1f}%",
                    extra=stats
                )
            elif memory_percent / 100 >= self.MEMORY_WARNING_THRESHOLD:
                stats['status'] = 'warning'
                logger.warning(
                    f"WARNING: Memory usage at {memory_percent:.1f}%",
                    extra=stats
                )

            return stats

        except Exception as e:
            logger.error(f"Error checking memory usage: {e}", exc_info=True)
            return {'error': str(e), 'status': 'unknown'}

    def cleanup_corpus(self, force=False) -> int:
        """
        Clean up old documents from corpus cache.

        Args:
            force (bool): Force cleanup regardless of size

        Returns:
            int: Number of documents removed
        """
        initial_size = len(self.corpus_cache)

        if force or len(self.corpus_cache) >= self.MAX_CORPUS_SIZE:
            # Remove oldest 25% of documents
            remove_count = max(1, len(self.corpus_cache) // 4)

            for _ in range(remove_count):
                if self.corpus_cache:
                    self.corpus_cache.popleft()

            removed = initial_size - len(self.corpus_cache)

            logger.info(
                f"Cleaned up corpus cache: removed {removed} documents",
                extra={
                    'initial_size': initial_size,
                    'final_size': len(self.corpus_cache),
                    'removed': removed
                }
            )

            # Force garbage collection
            gc.collect()

            return removed

        return 0

    def cleanup_old_models(self) -> int:
        """
        Remove unused or old models from cache.

        Returns:
            int: Number of models removed
        """
        if not self.model_cache:
            return 0

        cutoff_time = datetime.now() - timedelta(hours=self.MAX_CACHE_AGE_HOURS)
        initial_count = len(self.model_cache)
        models_to_remove = []

        # Find models older than cutoff
        for model_name, model_data in self.model_cache.items():
            if 'last_used' in model_data:
                if model_data['last_used'] < cutoff_time:
                    models_to_remove.append(model_name)

        # Remove old models
        for model_name in models_to_remove:
            del self.model_cache[model_name]

        removed = len(models_to_remove)

        if removed > 0:
            logger.info(
                f"Cleaned up model cache: removed {removed} models",
                extra={
                    'initial_count': initial_count,
                    'final_count': len(self.model_cache),
                    'removed': removed,
                    'models_removed': models_to_remove
                }
            )

            # Force garbage collection
            gc.collect()

        return removed

    def perform_cleanup(self, force=False) -> Dict[str, int]:
        """
        Perform complete cleanup of all caches.

        Args:
            force (bool): Force cleanup regardless of thresholds

        Returns:
            dict: Cleanup statistics
        """
        memory_stats = self.check_memory_usage()

        # Decide whether to cleanup
        should_cleanup = force or memory_stats.get('status') in ['warning', 'critical']

        if not should_cleanup:
            return {
                'corpus_removed': 0,
                'models_removed': 0,
                'memory_before': memory_stats.get('process_memory_mb', 0),
                'memory_after': memory_stats.get('process_memory_mb', 0)
            }

        memory_before = memory_stats.get('process_memory_mb', 0)

        # Cleanup corpus and models
        corpus_removed = self.cleanup_corpus(force=force)
        models_removed = self.cleanup_old_models()

        # Force garbage collection
        gc.collect()

        # Check memory after cleanup
        memory_after_stats = self.check_memory_usage()
        memory_after = memory_after_stats.get('process_memory_mb', 0)

        cleanup_stats = {
            'corpus_removed': corpus_removed,
            'models_removed': models_removed,
            'memory_before': memory_before,
            'memory_after': memory_after,
            'memory_freed_mb': memory_before - memory_after,
            'timestamp': datetime.now().isoformat()
        }

        logger.info(
            f"Cleanup completed: freed {cleanup_stats['memory_freed_mb']:.2f}MB",
            extra=cleanup_stats
        )

        self.last_cleanup = datetime.now()

        return cleanup_stats

    def should_perform_periodic_cleanup(self) -> bool:
        """
        Check if periodic cleanup should be performed.

        Returns:
            bool: True if cleanup should be performed
        """
        hours_since_cleanup = (datetime.now() - self.last_cleanup).total_seconds() / 3600
        return hours_since_cleanup >= 1  # Cleanup every hour

    def add_to_corpus(self, document):
        """
        Add document to corpus cache with automatic cleanup.

        Args:
            document: Document to add
        """
        self.corpus_cache.append(document)

        # Check if cleanup is needed
        if len(self.corpus_cache) >= self.MAX_CORPUS_SIZE:
            self.cleanup_corpus()

    def cache_model(self, model_name: str, model):
        """
        Cache a model with metadata.

        Args:
            model_name (str): Model identifier
            model: Model object to cache
        """
        self.model_cache[model_name] = {
            'model': model,
            'last_used': datetime.now(),
            'created_at': datetime.now()
        }

    def get_cached_model(self, model_name: str):
        """
        Get cached model and update last_used timestamp.

        Args:
            model_name (str): Model identifier

        Returns:
            Model object or None
        """
        if model_name in self.model_cache:
            self.model_cache[model_name]['last_used'] = datetime.now()
            return self.model_cache[model_name]['model']
        return None


# Global memory manager instance
memory_manager = MemoryManager()


def get_memory_stats() -> Dict[str, any]:
    """
    Get current memory statistics.

    Returns:
        dict: Memory statistics
    """
    return memory_manager.check_memory_usage()


def cleanup_memory(force=False) -> Dict[str, int]:
    """
    Perform memory cleanup.

    Args:
        force (bool): Force cleanup

    Returns:
        dict: Cleanup statistics
    """
    return memory_manager.perform_cleanup(force=force)


def periodic_cleanup_if_needed():
    """
    Perform periodic cleanup if needed.
    Should be called from background tasks or schedulers.
    """
    if memory_manager.should_perform_periodic_cleanup():
        return memory_manager.perform_cleanup()
    return None
