"""
Health endpoints for the indexing backend.
Implements monitoring-contract/v1 while keeping /health as a readiness alias.
"""

import os
import time
import logging
from datetime import datetime, timezone
from typing import Any

import psutil
import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"
CONTRACT_VERSION = "monitoring-contract/v1"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def component(status: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status}
    payload.update({k: v for k, v in fields.items() if v is not None})
    return payload


def aggregate_status(checks: dict[str, dict[str, Any]]) -> str:
    statuses = [check.get("status", UNHEALTHY) for check in checks.values()]
    if any(status == UNHEALTHY for status in statuses):
        return UNHEALTHY
    if any(status == DEGRADED for status in statuses):
        return DEGRADED
    return HEALTHY


def status_code(status: str) -> int:
    return 503 if status == UNHEALTHY else 200


def release_metadata() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": os.getenv("RELEASE_VERSION", "unknown"),
    }
    commit_sha = os.getenv("RELEASE_COMMIT_SHA")
    deployed_at = os.getenv("RELEASE_DEPLOYED_AT")
    if commit_sha and commit_sha != "unknown":
        payload["commitSha"] = commit_sha
    if deployed_at and deployed_at != "unknown":
        payload["deployedAt"] = deployed_at
    return payload


def operations_metadata() -> dict[str, Any]:
    payload = {
        "owner": os.getenv("SERVICE_OWNER"),
        "runbook_url": os.getenv("RUNBOOK_URL"),
        "dashboard_service_id": os.getenv("DASHBOARD_SERVICE_ID"),
        "repository_url": os.getenv("REPOSITORY_URL"),
        "public_base_url": os.getenv("PUBLIC_BASE_URL"),
    }
    return {k: v for k, v in payload.items() if v}


def build_contract_payload(
    *,
    endpoint_label: str,
    checks: dict[str, dict[str, Any]],
    status: str | None = None,
    journey: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_status = status or aggregate_status(checks)
    payload: dict[str, Any] = {
        "version": CONTRACT_VERSION,
        "service": {
            "id": os.getenv("SERVICE_IDENTIFIER", "lawa-agent-studio-indexing"),
            "name": os.getenv("SERVICE_DISPLAY_NAME", "LAWA Agent Studio Indexing"),
            "type": os.getenv("SERVICE_TYPE", "generic"),
            "environment": os.getenv("SERVICE_ENVIRONMENT", os.getenv("ENVIRONMENT", "unknown")),
        },
        "status": resolved_status,
        "summary": f"{endpoint_label} checks {'passed' if resolved_status == HEALTHY else 'degraded' if resolved_status == DEGRADED else 'failed'}",
        "timestamp": utc_timestamp(),
        "checks": checks,
        "release": release_metadata(),
    }
    operations = operations_metadata()
    if operations:
        payload["operations"] = operations
    if journey is not None:
        payload["journey"] = journey
    return payload


def database_check() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return component(HEALTHY if latency_ms < 1000 else DEGRADED, latency_ms=latency_ms)
    except Exception as exc:
        logger.error(f"Indexing DB health check failed: {exc}")
        return component(UNHEALTHY, error=str(exc))


def django_backend_check() -> dict[str, Any]:
    started = time.perf_counter()
    backend_url = os.getenv("DJANGO_BACKEND_URL", "http://localhost:8000").rstrip("/")
    target_url = f"{backend_url}/health/live"
    try:
        response = requests.get(target_url, timeout=5)
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        reported_status = payload.get("status")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code == 200 and reported_status in {HEALTHY, "alive", "ready"}:
            return component(HEALTHY, latency_ms=latency_ms, url=target_url)
        return component(
            DEGRADED,
            latency_ms=latency_ms,
            url=target_url,
            error=f"unexpected response {response.status_code} status={reported_status}",
        )
    except Exception as exc:
        return component(UNHEALTHY, url=target_url, error=str(exc))


def system_check() -> dict[str, Any]:
    try:
        cpu_percent = psutil.cpu_percent(interval=0.2)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        status = HEALTHY
        if cpu_percent > 90 or memory.percent > 90 or disk.percent > 90:
            status = UNHEALTHY
        elif cpu_percent > 80 or memory.percent > 80 or disk.percent > 80:
            status = DEGRADED
        return component(
            status,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            memory_available_gb=round(memory.available / (1024**3), 2),
            disk_percent=disk.percent,
            disk_free_gb=round(disk.free / (1024**3), 2),
        )
    except Exception as exc:
        return component(UNHEALTHY, error=str(exc))


def dependency_config_check(env_key: str, dependency_name: str) -> dict[str, Any]:
    value = os.getenv(env_key)
    if value:
        return component(HEALTHY, configured=True, dependency=dependency_name)
    return component(DEGRADED, configured=False, dependency=dependency_name, error=f"{env_key} not configured")


@router.get("/health")
async def health_check():
    return await health_ready()


@router.get("/health/live")
async def health_live():
    checks = {
        "application": component(HEALTHY),
        "process": component(HEALTHY, pid=os.getpid()),
        "contract": component(HEALTHY, version=CONTRACT_VERSION),
    }
    payload = build_contract_payload(endpoint_label="live", checks=checks, status=HEALTHY)
    return payload


@router.get("/health/ready")
async def health_ready():
    checks = {
        "database": database_check(),
        "external_services": {
            "status": HEALTHY,
            "django_backend": django_backend_check(),
        },
    }
    checks["external_services"]["status"] = aggregate_status(
        {"django_backend": checks["external_services"]["django_backend"]}
    )
    overall = aggregate_status(
        {
            "database": checks["database"],
            "external_services": checks["external_services"],
        }
    )
    payload = build_contract_payload(endpoint_label="ready", checks=checks, status=overall)
    return JSONResponse(status_code=status_code(overall), content=payload)


@router.get("/health/detailed")
async def health_detailed():
    checks = {
        "database": database_check(),
        "external_services": {
            "status": HEALTHY,
            "django_backend": django_backend_check(),
            "pinecone": dependency_config_check("PINECONE_API_KEY", "pinecone"),
            "gemini": dependency_config_check("GEMINI_API_KEY", "gemini"),
        },
        "system": system_check(),
    }
    checks["external_services"]["status"] = aggregate_status(
        {
            "django_backend": checks["external_services"]["django_backend"],
            "pinecone": checks["external_services"]["pinecone"],
            "gemini": checks["external_services"]["gemini"],
        }
    )
    overall = aggregate_status(
        {
            "database": checks["database"],
            "external_services": checks["external_services"],
            "system": checks["system"],
        }
    )
    payload = build_contract_payload(endpoint_label="detailed", checks=checks, status=overall)
    return JSONResponse(status_code=status_code(overall), content=payload)
