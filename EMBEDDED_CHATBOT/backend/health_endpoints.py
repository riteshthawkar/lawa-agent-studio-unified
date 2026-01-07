"""
Health Check Endpoints for Chatbot Backend
Provides health monitoring for the chatbot service.
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from modules.database.database import connect_db
from modules.config import get_config, INTEGRATION_MODE
from modules.lawa_integration import LawaIntegration

logger = logging.getLogger(__name__)
router = APIRouter()

# Global instances
db_pool = None
lawa_integration = None

async def get_db_pool():
    """Get or create database pool instance."""
    global db_pool
    if db_pool is None:
        db_pool = await connect_db()
    return db_pool

async def get_lawa_integration():
    """Get or create LAWA integration instance."""
    global lawa_integration
    if lawa_integration is None and INTEGRATION_MODE == "lawa":
        lawa_integration = LawaIntegration()
        await lawa_integration.initialize()
    return lawa_integration

@router.get("/health")
async def health_check():
    """
    Basic health check endpoint.
    Returns 200 if service is running.
    """
    return {
        "status": "healthy",
        "service": "lawa-chatbot-backend",
        "integration_mode": INTEGRATION_MODE,
        "timestamp": datetime.utcnow().isoformat()
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
        # Check database connectivity
        db_start = time.time()
        try:
            db_pool = await get_db_pool()
            if db_pool:
                async with db_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                db_duration = (time.time() - db_start) * 1000
                
                checks["database"] = {
                    "status": "healthy" if db_duration < 1000 else "degraded",
                    "response_time_ms": db_duration,
                    "message": "Database connected successfully"
                }
            else:
                checks["database"] = {
                    "status": "unhealthy",
                    "message": "Database pool not initialized"
                }
                overall_status = "unhealthy"
        except Exception as e:
            checks["database"] = {
                "status": "unhealthy",
                "message": f"Database connection failed: {str(e)}"
            }
            overall_status = "unhealthy"
        
        # Check Pinecone connectivity
        pinecone_start = time.time()
        try:
            from pinecone import Pinecone
            config = get_config()
            pc = Pinecone(api_key=config.PINECONE_API_KEY)
            
            if INTEGRATION_MODE == "lawa":
                # LAWA mode - single unified index
                index = pc.Index(config.PINECONE_INDEX_NAME)
            else:
                # Legacy mode - separate indexes
                summary_index = pc.Index(config.PINECONE_SUMMARY_INDEX)
                text_index = pc.Index(config.PINECONE_TEXT_INDEX)
                index = summary_index  # Use summary index for stats
            
            # Test index stats
            stats = index.describe_index_stats()
            pinecone_duration = (time.time() - pinecone_start) * 1000
            
            checks["pinecone"] = {
                "status": "healthy" if pinecone_duration < 2000 else "degraded",
                "response_time_ms": pinecone_duration,
                "message": "Pinecone connected successfully",
                "details": {
                    "integration_mode": INTEGRATION_MODE,
                    "total_vector_count": stats.get("total_vector_count", 0),
                    "dimension": stats.get("dimension", 0)
                }
            }
        except Exception as e:
            checks["pinecone"] = {
                "status": "unhealthy",
                "message": f"Pinecone connection failed: {str(e)}"
            }
            overall_status = "unhealthy"
        
        # Check LAWA integration (if enabled)
        if INTEGRATION_MODE == "lawa":
            lawa_start = time.time()
            try:
                lawa_integration = await get_lawa_integration()
                if lawa_integration and lawa_integration.enabled:
                    # Test LAWA database connection
                    async with lawa_integration.pool.acquire() as conn:
                        await conn.fetchval("SELECT COUNT(*) FROM chatbots LIMIT 1")
                    
                    lawa_duration = (time.time() - lawa_start) * 1000
                    
                    checks["lawa_integration"] = {
                        "status": "healthy" if lawa_duration < 1000 else "degraded",
                        "response_time_ms": lawa_duration,
                        "message": "LAWA integration connected successfully"
                    }
                else:
                    checks["lawa_integration"] = {
                        "status": "unhealthy",
                        "message": "LAWA integration not enabled or failed to initialize"
                    }
                    overall_status = "unhealthy"
            except Exception as e:
                checks["lawa_integration"] = {
                    "status": "unhealthy",
                    "message": f"LAWA integration failed: {str(e)}"
                }
                overall_status = "unhealthy"
        
        # Check external services
        external_start = time.time()
        try:
            import requests
            
            # Check Django backend
            config = get_config()
            django_url = getattr(config, 'DJANGO_BACKEND_URL', 'http://localhost:8001')
            django_response = requests.get(f"{django_url}/health", timeout=5)
            django_healthy = django_response.status_code == 200
            
            external_duration = (time.time() - external_start) * 1000
            
            checks["external_services"] = {
                "status": "healthy" if django_healthy else "degraded",
                "response_time_ms": external_duration,
                "message": "External services check completed",
                "details": {
                    "django_backend": "healthy" if django_healthy else "unhealthy"
                }
            }
            
            if not django_healthy:
                overall_status = "degraded"
                
        except Exception as e:
            checks["external_services"] = {
                "status": "unhealthy",
                "message": f"External services check failed: {str(e)}"
            }
            overall_status = "unhealthy"
        
        # Check system resources
        try:
            import psutil
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percentage = memory.percent
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_percentage = (disk.used / disk.total) * 100
            
            checks["system_resources"] = {
                "status": "healthy" if memory_percentage < 80 and disk_percentage < 80 else "degraded",
                "message": f"Memory: {memory_percentage:.1f}%, Disk: {disk_percentage:.1f}%",
                "details": {
                    "memory_percentage": memory_percentage,
                    "disk_percentage": disk_percentage,
                    "available_memory_gb": memory.available / (1024**3),
                    "available_disk_gb": disk.free / (1024**3)
                }
            }
            
            if memory_percentage > 90 or disk_percentage > 90:
                overall_status = "unhealthy"
                
        except Exception as e:
            checks["system_resources"] = {
                "status": "unhealthy",
                "message": f"System resource check failed: {str(e)}"
            }
            overall_status = "unhealthy"
        
        total_duration = (time.time() - start_time) * 1000
        
        return {
            "status": overall_status,
            "service": "lawa-chatbot-backend",
            "integration_mode": INTEGRATION_MODE,
            "timestamp": datetime.utcnow().isoformat(),
            "duration_ms": total_duration,
            "checks": checks,
            "summary": {
                "healthy": sum(1 for check in checks.values() if check["status"] == "healthy"),
                "degraded": sum(1 for check in checks.values() if check["status"] == "degraded"),
                "unhealthy": sum(1 for check in checks.values() if check["status"] == "unhealthy")
            }
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "lawa-chatbot-backend",
            "integration_mode": INTEGRATION_MODE,
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "checks": checks
        }

@router.get("/health/ready")
async def health_ready():
    """
    Readiness probe for Kubernetes.
    Returns 200 if service is ready to accept traffic.
    """
    try:
        # Check critical dependencies
        db_pool = await get_db_pool()
        if not db_pool:
            raise HTTPException(status_code=503, detail="Database not ready")
        
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "ready",
            "service": "lawa-chatbot-backend",
            "integration_mode": INTEGRATION_MODE
        }
        
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "error": str(e),
                "service": "lawa-chatbot-backend"
            }
        )

@router.get("/health/live")
async def health_live():
    """
    Liveness probe for Kubernetes.
    Returns 200 if service is alive (not deadlocked).
    """
    return {
        "status": "alive",
        "service": "lawa-chatbot-backend",
        "integration_mode": INTEGRATION_MODE
    }
