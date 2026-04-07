"""
Health Check Endpoints for Website Indexing Backend
Provides health monitoring for the indexing service.
"""

import time
import logging
import psutil
import httpx
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from modules.django_database import db_manager
from modules.config import get_config

logger = logging.getLogger(__name__)
router = APIRouter()


async def check_database_health() -> Dict[str, Any]:
    """Run an async-safe database probe through the shared Django DB manager."""
    db_start = time.time()

    try:
        await db_manager.get_task_stats()
        db_duration = (time.time() - db_start) * 1000
        return {
            "status": "healthy" if db_duration < 1000 else "degraded",
            "response_time_ms": db_duration,
            "message": "Django database connected successfully",
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "response_time_ms": (time.time() - db_start) * 1000,
            "message": f"Database connection failed: {exc}",
        }


async def check_django_backend_health() -> Dict[str, Any]:
    """Verify the indexing service can reach the Django core backend."""
    config = get_config()
    django_url = config.django_backend_url.rstrip("/")
    health_url = f"{django_url}/health/"
    start = time.time()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_url)

        duration = (time.time() - start) * 1000
        if response.status_code == 200:
            return {
                "status": "healthy" if duration < 1000 else "degraded",
                "response_time_ms": duration,
                "message": "Django backend reachable",
                "url": health_url,
            }

        return {
            "status": "unhealthy",
            "response_time_ms": duration,
            "message": f"Django backend returned {response.status_code}",
            "url": health_url,
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "response_time_ms": (time.time() - start) * 1000,
            "message": f"Django backend check failed: {exc}",
            "url": health_url,
        }


@router.get("/health")
async def health_check():
    """
    Basic health check endpoint.
    Returns 200 if service is running.
    """
    return {
        "status": "healthy",
        "service": "lawa-indexing-backend",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/health/detailed")
async def health_detailed():
    """
    Detailed health check endpoint.
    Returns comprehensive health status.
    """
    start_time = time.time()
    checks = {}
    overall_status = "healthy"
    
    try:
        checks["database"] = await check_database_health()
        if checks["database"]["status"] == "unhealthy":
            overall_status = "degraded"
        
        # Check system resources
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            checks["system"] = {
                "status": "healthy",
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024**3)
            }
            
            if cpu_percent > 90 or memory.percent > 90 or disk.percent > 90:
                overall_status = "degraded"
                
        except Exception as e:
            checks["system"] = {
                "status": "unhealthy",
                "message": f"System check failed: {str(e)}"
            }
            overall_status = "degraded"
        
        django_backend = await check_django_backend_health()
        checks["external_services"] = {
            "django_backend": django_backend,
            "pinecone": {
                "status": "unknown",
                "message": "Pinecone status not checked (requires API key)"
            },
            "gemini": {
                "status": "unknown",
                "message": "Gemini status not checked (requires API key)"
            }
        }

        if django_backend["status"] == "unhealthy":
            overall_status = "degraded"
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        overall_status = "unhealthy"
        checks["error"] = {
            "status": "unhealthy",
            "message": f"Health check failed: {str(e)}"
        }
    
    total_duration = (time.time() - start_time) * 1000
    
    return {
        "status": overall_status,
        "service": "lawa-indexing-backend",
        "timestamp": datetime.now().isoformat(),
        "response_time_ms": total_duration,
        "checks": checks
    }


@router.get("/health/ready")
async def health_ready():
    """
    Readiness check endpoint.
    Returns 200 if service is ready to accept requests.
    """
    try:
        db_health = await check_database_health()
        if db_health["status"] == "unhealthy":
            raise RuntimeError(db_health["message"])
        
        return {
            "status": "ready",
            "service": "lawa-indexing-backend",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Service not ready: {str(e)}"
        )


@router.get("/health/live")
async def health_live():
    """
    Liveness check endpoint.
    Returns 200 if service is alive.
    """
    return {
        "status": "alive",
        "service": "lawa-indexing-backend",
        "timestamp": datetime.now().isoformat()
    }
