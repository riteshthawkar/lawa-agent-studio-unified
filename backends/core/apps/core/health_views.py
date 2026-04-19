"""
Health Check Views for LAWA Platform
Provides health monitoring endpoints for all services.
"""

import os
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from .health_checks import get_health_status
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"
CONTRACT_VERSION = "monitoring-contract/v1"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def aggregate_status(checks: dict) -> str:
    statuses = [check.get("status", UNHEALTHY) for check in checks.values() if isinstance(check, dict)]
    if any(state == UNHEALTHY for state in statuses):
        return UNHEALTHY
    if any(state == DEGRADED for state in statuses):
        return DEGRADED
    return HEALTHY


def release_metadata() -> dict:
    payload = {
        "version": os.getenv("RELEASE_VERSION", "unknown"),
    }
    commit_sha = os.getenv("RELEASE_COMMIT_SHA")
    deployed_at = os.getenv("RELEASE_DEPLOYED_AT")
    if commit_sha and commit_sha != "unknown":
        payload["commitSha"] = commit_sha
    if deployed_at and deployed_at != "unknown":
        payload["deployedAt"] = deployed_at
    return payload


def operations_metadata() -> dict:
    payload = {
        "owner": os.getenv("SERVICE_OWNER"),
        "runbook_url": os.getenv("RUNBOOK_URL"),
        "dashboard_service_id": os.getenv("DASHBOARD_SERVICE_ID"),
        "repository_url": os.getenv("REPOSITORY_URL"),
        "public_base_url": os.getenv("PUBLIC_BASE_URL"),
    }
    return {k: v for k, v in payload.items() if v}


def contract_payload(endpoint_label: str, checks: dict, resolved_status: str | None = None) -> dict:
    status_value = resolved_status or aggregate_status(checks)
    payload = {
        "version": CONTRACT_VERSION,
        "service": {
            "id": os.getenv("SERVICE_IDENTIFIER", "lawa-agent-studio-core"),
            "name": os.getenv("SERVICE_DISPLAY_NAME", "LAWA Agent Studio Core"),
            "type": os.getenv("SERVICE_TYPE", "generic"),
            "environment": os.getenv("SERVICE_ENVIRONMENT", os.getenv("ENVIRONMENT", "unknown")),
        },
        "status": status_value,
        "summary": f"{endpoint_label} checks {'passed' if status_value == HEALTHY else 'degraded' if status_value == DEGRADED else 'failed'}",
        "timestamp": utc_timestamp(),
        "checks": checks,
        "release": release_metadata(),
    }
    operations = operations_metadata()
    if operations:
        payload["operations"] = operations
    return payload


def contract_http_status(status_value: str) -> int:
    return status.HTTP_503_SERVICE_UNAVAILABLE if status_value == UNHEALTHY else status.HTTP_200_OK

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Basic health check endpoint.
    Returns 200 if service is running.
    """
    return health_ready(request)

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
        
        payload = contract_payload(
            endpoint_label="detailed",
            checks=health_data.get("checks", {}),
            resolved_status=health_data.get("status", UNHEALTHY),
        )
        return Response(payload, status=contract_http_status(payload["status"]))
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        payload = contract_payload(
            endpoint_label="detailed",
            checks={"application": {"status": UNHEALTHY, "error": str(e)}},
            resolved_status=UNHEALTHY,
        )
        return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)

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
        
        checks = {
            "database": {"status": HEALTHY},
        }
        payload = contract_payload(endpoint_label="ready", checks=checks, resolved_status=HEALTHY)
        return Response(payload, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        checks = {
            "database": {"status": UNHEALTHY, "error": str(e)},
        }
        payload = contract_payload(endpoint_label="ready", checks=checks, resolved_status=UNHEALTHY)
        return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)

@api_view(['GET'])
@permission_classes([AllowAny])
def health_live(request):
    """
    Liveness probe for Kubernetes.
    Returns 200 if service is alive (not deadlocked).
    """
    checks = {
        "application": {"status": HEALTHY},
        "process": {"status": HEALTHY, "pid": os.getpid()},
        "contract": {"status": HEALTHY, "version": CONTRACT_VERSION},
    }
    payload = contract_payload(endpoint_label="live", checks=checks, resolved_status=HEALTHY)
    return Response(payload, status=status.HTTP_200_OK)
