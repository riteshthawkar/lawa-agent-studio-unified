"""
Health endpoints for the chatbot widget backend.
Implements monitoring-contract/v1 with backward compatibility for /health.
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
from openai import AsyncOpenAI
from pinecone import Pinecone

from modules.database.database import connect_db
from modules.config import get_config, INTEGRATION_MODE, OPENAI_TIMEOUT
from modules.lawa_integration import LawaIntegration

logger = logging.getLogger(__name__)
router = APIRouter()

HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"
CONTRACT_VERSION = "monitoring-contract/v1"

# Global lazy singletons
db_pool = None
lawa_integration = None
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
            "id": os.getenv("SERVICE_IDENTIFIER", "lawa-agent-studio-widget"),
            "name": os.getenv("SERVICE_DISPLAY_NAME", "LAWA Agent Studio Chatbot"),
            "type": os.getenv("SERVICE_TYPE", "rag"),
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


async def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await connect_db()
    return db_pool


async def get_lawa_integration():
    global lawa_integration
    if lawa_integration is None and INTEGRATION_MODE == "lawa":
        lawa_integration = LawaIntegration()
        await lawa_integration.initialize()
    return lawa_integration


async def database_check() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        pool = await get_db_pool()
        if not pool:
            return component(UNHEALTHY, error="database pool not initialized")
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return component(HEALTHY if latency_ms < 1000 else DEGRADED, latency_ms=latency_ms)
    except Exception as exc:
        return component(UNHEALTHY, error=str(exc))


def pinecone_check() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        config = get_config()
        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        if INTEGRATION_MODE == "lawa":
            index = pc.Index(config.PINECONE_INDEX_NAME)
        else:
            index = pc.Index(config.PINECONE_SUMMARY_INDEX)
        stats = index.describe_index_stats()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        total_vector_count = stats.get("total_vector_count", 0) if isinstance(stats, dict) else None
        return component(
            HEALTHY if latency_ms < 2000 else DEGRADED,
            latency_ms=latency_ms,
            integration_mode=INTEGRATION_MODE,
            total_vector_count=total_vector_count,
        )
    except Exception as exc:
        return component(UNHEALTHY, error=str(exc))


def openai_config_check() -> dict[str, Any]:
    model = os.getenv("GENERATION_MODEL", "gpt-4o")
    if not os.getenv("OPENAI_API_KEY"):
        return component(UNHEALTHY, error="OPENAI_API_KEY is not configured")
    return component(HEALTHY, generation_model=model)


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


async def lawa_integration_check() -> dict[str, Any]:
    if INTEGRATION_MODE != "lawa":
        return component(HEALTHY, mode="legacy")
    started = time.perf_counter()
    try:
        integration = await get_lawa_integration()
        if not integration or not integration.enabled:
            return component(UNHEALTHY, error="LAWA integration not enabled")
        async with integration.pool.acquire() as conn:
            await conn.fetchval("SELECT COUNT(*) FROM chatbots LIMIT 1")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return component(HEALTHY if latency_ms < 1000 else DEGRADED, latency_ms=latency_ms, mode="lawa")
    except Exception as exc:
        return component(UNHEALTHY, error=str(exc), mode="lawa")


def system_resources_check() -> dict[str, Any]:
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        memory_pct = memory.percent
        disk_pct = disk.percent
        status = HEALTHY
        if memory_pct > 90 or disk_pct > 90:
            status = UNHEALTHY
        elif memory_pct > 80 or disk_pct > 80:
            status = DEGRADED
        return component(
            status,
            memory_percentage=memory_pct,
            disk_percentage=disk_pct,
            available_memory_gb=round(memory.available / (1024**3), 2),
            available_disk_gb=round(disk.free / (1024**3), 2),
        )
    except Exception as exc:
        return component(UNHEALTHY, error=str(exc))


async def journey_probe() -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    started = time.perf_counter()
    checks = {
        "database": await database_check(),
        "pinecone": pinecone_check(),
        "openai": openai_config_check(),
        "lawa_integration": await lawa_integration_check(),
    }
    preflight = aggregate_status(checks)
    model = os.getenv("GENERATION_MODEL", "gpt-4o")
    if preflight == UNHEALTHY:
        return (
            {
                "name": "llm_generation",
                "status": UNHEALTHY,
                "probeModeSupported": True,
                "sideEffects": "none",
                "durationMs": int((time.perf_counter() - started) * 1000),
                "message": "preflight dependency checks failed",
            },
            checks,
            UNHEALTHY,
        )

    try:
        completion = await openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a health probe. Reply with exactly: OK"},
                {"role": "user", "content": "Probe"},
            ],
            temperature=0,
            max_tokens=8,
            timeout=OPENAI_TIMEOUT,
        )
        content = completion.choices[0].message.content if completion and completion.choices else ""
        probe_text = (content or "").strip()
        if not probe_text:
            checks["journey_generation"] = component(UNHEALTHY, error="empty generation output", model=model)
            journey_status = UNHEALTHY
            journey_message = "generation returned empty output"
        else:
            checks["journey_generation"] = component(HEALTHY, model=model, preview=probe_text[:80])
            journey_status = aggregate_status(checks)
            journey_message = "generation path healthy"
    except Exception as exc:
        checks["journey_generation"] = component(UNHEALTHY, model=model, error=str(exc))
        journey_status = UNHEALTHY
        journey_message = str(exc)

    journey = {
        "name": "llm_generation",
        "status": journey_status,
        "probeModeSupported": True,
        "sideEffects": "none",
        "durationMs": int((time.perf_counter() - started) * 1000),
        "message": journey_message[:200],
    }
    return journey, checks, journey_status


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
        "database": await database_check(),
        "pinecone": pinecone_check(),
        "openai": openai_config_check(),
        "lawa_integration": await lawa_integration_check(),
    }
    overall = aggregate_status(checks)
    payload = build_contract_payload(endpoint_label="ready", checks=checks, status=overall)
    return JSONResponse(status_code=status_code(overall), content=payload)


@router.get("/health/detailed")
async def health_detailed():
    checks = {
        "database": await database_check(),
        "pinecone": pinecone_check(),
        "openai": openai_config_check(),
        "lawa_integration": await lawa_integration_check(),
        "external_services": {
            "status": HEALTHY,
            "django_backend": django_backend_check(),
        },
        "system_resources": system_resources_check(),
    }
    checks["external_services"]["status"] = aggregate_status(
        {"django_backend": checks["external_services"]["django_backend"]}
    )
    overall = aggregate_status(
        {
            "database": checks["database"],
            "pinecone": checks["pinecone"],
            "openai": checks["openai"],
            "lawa_integration": checks["lawa_integration"],
            "external_services": checks["external_services"],
            "system_resources": checks["system_resources"],
        }
    )
    payload = build_contract_payload(endpoint_label="detailed", checks=checks, status=overall)
    return JSONResponse(status_code=status_code(overall), content=payload)


@router.get("/health/journey")
async def health_journey():
    journey, checks, overall = await journey_probe()
    payload = build_contract_payload(
        endpoint_label="journey",
        checks=checks,
        status=overall,
        journey=journey,
    )
    return JSONResponse(status_code=status_code(overall), content=payload)
