"""
Health Check Endpoints for Website Indexing Backend
Provides health monitoring for the indexing service.
"""

import time
import logging
import psutil
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from modules.django_database import db_manager

logger = logging.getLogger(__name__)
router = APIRouter()


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
        # Check database connectivity (Django ORM)
        db_start = time.time()
        
        try:
            # Test Django database connection
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            
            db_duration = (time.time() - db_start) * 1000
            
            checks["database"] = {
                "status": "healthy" if db_duration < 1000 else "degraded",
                "response_time_ms": db_duration,
                "message": "Django database connected successfully"
            }
        except Exception as e:
            checks["database"] = {
                "status": "unhealthy",
                "response_time_ms": (time.time() - db_start) * 1000,
                "message": f"Database connection failed: {str(e)}"
            }
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
        
        # Check external services
        checks["external_services"] = {
            "pinecone": {
                "status": "unknown",
                "message": "Pinecone status not checked (requires API key)"
            },
            "gemini": {
                "status": "unknown", 
                "message": "Gemini status not checked (requires API key)"
            }
        }
        
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
        # Check if Django database is accessible
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        
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