"""
Health Check Module for LAWA Platform
Provides comprehensive health monitoring for all services.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from django.db import connection
from django.core.cache import cache
from django.conf import settings
import requests
import asyncio
import asyncpg

logger = logging.getLogger(__name__)

class HealthCheckResult:
    """Result of a health check."""
    
    def __init__(self, name: str, status: str, message: str = "", details: Dict[str, Any] = None):
        self.name = name
        self.status = status  # "healthy", "degraded", "unhealthy"
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow()
        self.duration_ms = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms
        }

class HealthChecker:
    """Centralized health checking for all services."""
    
    def __init__(self):
        self.checks = []
        self._register_default_checks()
    
    def _register_default_checks(self):
        """Register default health checks."""
        self.checks = [
            self._check_database,
            self._check_cache,
            self._check_external_services,
            self._check_disk_space,
            self._check_memory_usage,
        ]
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks and return comprehensive status."""
        start_time = time.time()
        results = []
        overall_status = "healthy"
        
        for check in self.checks:
            try:
                result = await check()
                results.append(result)
                
                # Update overall status based on individual results
                if result.status == "unhealthy":
                    overall_status = "unhealthy"
                elif result.status == "degraded" and overall_status == "healthy":
                    overall_status = "degraded"
                    
            except Exception as e:
                logger.error(f"Health check {check.__name__} failed: {e}")
                error_result = HealthCheckResult(
                    name=check.__name__,
                    status="unhealthy",
                    message=f"Check failed: {str(e)}"
                )
                results.append(error_result)
                overall_status = "unhealthy"
        
        total_duration = (time.time() - start_time) * 1000
        
        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_ms": total_duration,
            "checks": [result.to_dict() for result in results],
            "summary": self._generate_summary(results)
        }
    
    def _generate_summary(self, results: List[HealthCheckResult]) -> Dict[str, int]:
        """Generate summary statistics."""
        summary = {"healthy": 0, "degraded": 0, "unhealthy": 0}
        for result in results:
            summary[result.status] += 1
        return summary
    
    async def _check_database(self) -> HealthCheckResult:
        """Check database connectivity and performance."""
        start_time = time.time()
        
        try:
            with connection.cursor() as cursor:
                # Test basic connectivity
                cursor.execute("SELECT 1")
                cursor.fetchone()
                
                # Test query performance
                cursor.execute("SELECT COUNT(*) FROM django_migrations")
                migration_count = cursor.fetchone()[0]
                
                # Test write operation (if possible)
                cursor.execute("SELECT NOW()")
                current_time = cursor.fetchone()[0]
                
                duration = (time.time() - start_time) * 1000
                
                return HealthCheckResult(
                    name="database",
                    status="healthy" if duration < 1000 else "degraded",
                    message=f"Database connected successfully",
                    details={
                        "response_time_ms": duration,
                        "migration_count": migration_count,
                        "current_time": current_time.isoformat() if current_time else None
                    }
                )
                
        except Exception as e:
            return HealthCheckResult(
                name="database",
                status="unhealthy",
                message=f"Database connection failed: {str(e)}",
                details={"error": str(e)}
            )
    
    async def _check_cache(self) -> HealthCheckResult:
        """Check cache connectivity and performance."""
        start_time = time.time()
        
        try:
            # Test cache write/read
            test_key = f"health_check_{int(time.time())}"
            test_value = "test_value"
            
            cache.set(test_key, test_value, timeout=60)
            retrieved_value = cache.get(test_key)
            cache.delete(test_key)
            
            duration = (time.time() - start_time) * 1000
            
            if retrieved_value == test_value:
                return HealthCheckResult(
                    name="cache",
                    status="healthy" if duration < 100 else "degraded",
                    message="Cache is working correctly",
                    details={"response_time_ms": duration}
                )
            else:
                return HealthCheckResult(
                    name="cache",
                    status="unhealthy",
                    message="Cache read/write test failed"
                )
                
        except Exception as e:
            return HealthCheckResult(
                name="cache",
                status="unhealthy",
                message=f"Cache check failed: {str(e)}",
                details={"error": str(e)}
            )
    
    async def _check_external_services(self) -> HealthCheckResult:
        """Check external service dependencies."""
        start_time = time.time()
        
        services = {
            "indexing_backend": getattr(settings, 'INDEXING_SERVICE_URL', 'http://localhost:8000'),
            "chatbot_backend": getattr(settings, 'CHATBOT_SERVICE_URL', 'http://localhost:8002'),
        }
        
        results = {}
        overall_healthy = True
        
        for service_name, service_url in services.items():
            try:
                response = requests.get(f"{service_url}/health", timeout=5)
                if response.status_code == 200:
                    results[service_name] = "healthy"
                else:
                    results[service_name] = "degraded"
                    overall_healthy = False
            except Exception as e:
                results[service_name] = "unhealthy"
                overall_healthy = False
        
        duration = (time.time() - start_time) * 1000
        
        status = "healthy" if overall_healthy else "degraded"
        if any(status == "unhealthy" for status in results.values()):
            status = "unhealthy"
        
        return HealthCheckResult(
            name="external_services",
            status=status,
            message=f"External services check completed",
            details={
                "response_time_ms": duration,
                "services": results
            }
        )
    
    async def _check_disk_space(self) -> HealthCheckResult:
        """Check available disk space."""
        try:
            import shutil
            
            # Check disk space for the current directory
            total, used, free = shutil.disk_usage(".")
            free_percentage = (free / total) * 100
            
            if free_percentage > 20:
                status = "healthy"
            elif free_percentage > 10:
                status = "degraded"
            else:
                status = "unhealthy"
            
            return HealthCheckResult(
                name="disk_space",
                status=status,
                message=f"Disk space: {free_percentage:.1f}% free",
                details={
                    "free_percentage": free_percentage,
                    "free_bytes": free,
                    "total_bytes": total
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name="disk_space",
                status="unhealthy",
                message=f"Disk space check failed: {str(e)}",
                details={"error": str(e)}
            )
    
    async def _check_memory_usage(self) -> HealthCheckResult:
        """Check memory usage."""
        try:
            import psutil
            
            # Get memory usage
            memory = psutil.virtual_memory()
            memory_percentage = memory.percent
            
            if memory_percentage < 80:
                status = "healthy"
            elif memory_percentage < 90:
                status = "degraded"
            else:
                status = "unhealthy"
            
            return HealthCheckResult(
                name="memory_usage",
                status=status,
                message=f"Memory usage: {memory_percentage:.1f}%",
                details={
                    "memory_percentage": memory_percentage,
                    "available_bytes": memory.available,
                    "total_bytes": memory.total
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name="memory_usage",
                status="unhealthy",
                message=f"Memory check failed: {str(e)}",
                details={"error": str(e)}
            )

# Global health checker instance
health_checker = HealthChecker()

# Convenience function for views
async def get_health_status() -> Dict[str, Any]:
    """Get current health status of all services."""
    return await health_checker.run_all_checks()
