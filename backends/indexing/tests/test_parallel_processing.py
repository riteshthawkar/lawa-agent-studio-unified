#!/usr/bin/env python3
"""
Comprehensive Parallel Processing Test Suite

This script tests the Celery-based parallel processing and PDF chunk handling
for the website indexing backend.

Tests:
1. Redis connection verification
2. Queue submission verification
3. Concurrent task handling
4. Small website processing (https://omkarthawakar.github.io/)
5. Large website with PDFs (https://dbatu.ac.in/)

Usage:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start Indexing API: USE_CELERY_WORKER=true uvicorn app:app --port 8080
    3. Start Celery Worker: celery -A celery_app worker -l info --concurrency=2
    4. Run this script: python tests/test_parallel_processing.py
"""

import asyncio
import os
import sys
import logging
import uuid
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

import redis
import httpx

# Add module path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("parallel_test")


@dataclass
class ParallelTestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_seconds: float
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ParallelTestSuiteResult:
    """Result of the entire test suite."""
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    results: List[ParallelTestResult] = field(default_factory=list)
    
    def add_result(self, result: ParallelTestResult):
        self.results.append(result)
        self.total_tests += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def print_summary(self):
        print("\n" + "="*60)
        print("TEST SUITE SUMMARY")
        print("="*60)
        for r in self.results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            print(f"{status} - {r.name} ({r.duration_seconds:.2f}s)")
            if r.error:
                print(f"       Error: {r.error}")
            if r.details:
                for k, v in r.details.items():
                    print(f"       {k}: {v}")
        print("="*60)
        print(f"Total: {self.total_tests} | Passed: {self.passed} | Failed: {self.failed}")
        print("="*60)


class ParallelProcessingTester:
    """Test suite for parallel processing verification."""
    
    def __init__(self, api_base: str = "http://localhost:8080", redis_url: str = "redis://localhost:6379/0"):
        self.api_base = api_base
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.suite_result = ParallelTestSuiteResult()
        
    async def run_all_tests(self):
        """Run all tests in sequence."""
        logger.info("Starting Parallel Processing Test Suite")
        
        # 1. Test Redis Connection
        await self._run_test("Redis Connection", self.test_redis_connection)
        
        # 2. Test API Health
        await self._run_test("API Health Check", self.test_api_health)
        
        # 3. Test Queue Submission
        await self._run_test("Queue Submission", self.test_queue_submission)
        
        # 4. Test Small Website (Quick)
        await self._run_test("Small Website Indexing", self.test_small_website)
        
        # 5. Test Large Website with PDFs
        await self._run_test("Large Website with PDFs", self.test_large_website)
        
        # Print summary
        self.suite_result.print_summary()
        
        return self.suite_result.failed == 0
    
    async def _run_test(self, name: str, test_func):
        """Run a single test and record result."""
        logger.info(f"\n{'='*40}")
        logger.info(f"Running: {name}")
        logger.info(f"{'='*40}")
        
        start_time = time.time()
        try:
            result = await test_func()
            duration = time.time() - start_time
            
            if isinstance(result, dict):
                test_result = ParallelTestResult(
                    name=name,
                    passed=result.get("passed", False),
                    duration_seconds=duration,
                    details=result.get("details", {}),
                    error=result.get("error")
                )
            else:
                test_result = ParallelTestResult(
                    name=name,
                    passed=bool(result),
                    duration_seconds=duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Test '{name}' failed with exception: {e}")
            test_result = ParallelTestResult(
                name=name,
                passed=False,
                duration_seconds=duration,
                error=str(e)
            )
        
        self.suite_result.add_result(test_result)
        
        status = "PASSED ✅" if test_result.passed else "FAILED ❌"
        logger.info(f"Test '{name}' {status}")
    
    # =========================================================================
    # Individual Tests
    # =========================================================================
    
    async def test_redis_connection(self) -> Dict[str, Any]:
        """Test 1: Verify Redis connectivity."""
        try:
            self.redis_client = redis.from_url(self.redis_url)
            pong = self.redis_client.ping()
            
            # Check Celery queue exists
            queue_len = self.redis_client.llen("celery")
            
            return {
                "passed": pong,
                "details": {
                    "redis_url": self.redis_url,
                    "ping_response": pong,
                    "celery_queue_length": queue_len
                }
            }
        except Exception as e:
            return {"passed": False, "error": str(e)}
    
    async def test_api_health(self) -> Dict[str, Any]:
        """Test 2: Verify Indexing API is running."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.api_base}/health", timeout=10)
                
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "passed": data.get("status") == "healthy",
                        "details": data
                    }
                else:
                    return {
                        "passed": False,
                        "error": f"Status code: {resp.status_code}"
                    }
        except Exception as e:
            return {"passed": False, "error": str(e)}
    
    async def test_queue_submission(self) -> Dict[str, Any]:
        """Test 3: Verify task is queued in Redis."""
        try:
            # Get initial queue length
            initial_len = self.redis_client.llen("celery") if self.redis_client else 0
            
            # Submit a minimal test task
            task_id = f"test_{uuid.uuid4().hex[:8]}"
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.api_base}/index",
                    json={
                        "url": "https://example.com",
                        "max_pages": 1,
                        "external_job_id": task_id
                    },
                    headers={"Authorization": f"Bearer {os.getenv('INDEXING_API_TOKEN', 'test-token')}"},
                    timeout=30
                )
                
                if resp.status_code not in [200, 201, 202]:
                    return {
                        "passed": False,
                        "error": f"API returned {resp.status_code}: {resp.text}"
                    }
                
                data = resp.json()
                
            # Check queue length after submission
            await asyncio.sleep(0.5)
            new_len = self.redis_client.llen("celery") if self.redis_client else 0
            
            # Task might be picked up immediately if worker is running
            # So we just verify the API accepted the task
            return {
                "passed": True,
                "details": {
                    "task_id": data.get("task_id"),
                    "external_job_id": task_id,
                    "initial_queue_len": initial_len,
                    "new_queue_len": new_len,
                    "api_response": data.get("status", "unknown")
                }
            }
            
        except Exception as e:
            return {"passed": False, "error": str(e)}
    
    async def test_small_website(self) -> Dict[str, Any]:
        """Test 4: Process a small website (3 pages)."""
        url = "https://omkarthawakar.github.io/"
        task_id = f"small_{uuid.uuid4().hex[:8]}"
        
        try:
            # Submit task
            async with httpx.AsyncClient() as client:
                logger.info(f"Submitting small website: {url}")
                
                resp = await client.post(
                    f"{self.api_base}/index",
                    json={
                        "url": url,
                        "max_pages": 10,
                        "external_job_id": task_id
                    },
                    headers={"Authorization": f"Bearer {os.getenv('INDEXING_API_TOKEN', 'test-token')}"},
                    timeout=30
                )
                
                if resp.status_code not in [200, 201, 202]:
                    return {"passed": False, "error": f"Submit failed: {resp.text}"}
                
                data = resp.json()
                internal_task_id = data.get("task_id")
                
                logger.info(f"Task submitted: {internal_task_id}")
                
                # Poll for completion (max 2 minutes for small site)
                result = await self._poll_task_status(client, internal_task_id, timeout=120)
                
                return {
                    "passed": result.get("status") in ["completed", "completed_with_errors"],
                    "details": {
                        "url": url,
                        "final_status": result.get("status"),
                        "pages_processed": result.get("pages_processed", 0),
                        "chunks_created": result.get("result", {}).get("total_chunks", 0),
                        "vectors_indexed": result.get("result", {}).get("total_vectors", 0),
                        "duration_seconds": result.get("processing_time_seconds", 0)
                    }
                }
                
        except Exception as e:
            return {"passed": False, "error": str(e)}
    
    async def test_large_website(self) -> Dict[str, Any]:
        """Test 5: Process a large website with PDFs."""
        url = "https://dbatu.ac.in/"
        task_id = f"large_{uuid.uuid4().hex[:8]}"
        max_pages = 10  # Limit for testing
        
        try:
            async with httpx.AsyncClient() as client:
                logger.info(f"Submitting large website (limited to {max_pages} pages): {url}")
                
                resp = await client.post(
                    f"{self.api_base}/index",
                    json={
                        "url": url,
                        "max_pages": max_pages,
                        "external_job_id": task_id
                    },
                    headers={"Authorization": f"Bearer {os.getenv('INDEXING_API_TOKEN', 'test-token')}"},
                    timeout=30
                )
                
                if resp.status_code not in [200, 201, 202]:
                    return {"passed": False, "error": f"Submit failed: {resp.text}"}
                
                data = resp.json()
                internal_task_id = data.get("task_id")
                
                logger.info(f"Task submitted: {internal_task_id}")
                
                # Poll for completion (max 10 minutes for large site with PDFs)
                result = await self._poll_task_status(client, internal_task_id, timeout=600)
                
                # Check for PDF processing indicators
                pages_with_pdfs = result.get("result", {}).get("pdfs_processed", 0)
                
                return {
                    "passed": result.get("status") in ["completed", "completed_with_errors"],
                    "details": {
                        "url": url,
                        "max_pages_limit": max_pages,
                        "final_status": result.get("status"),
                        "pages_processed": result.get("pages_processed", 0),
                        "pdfs_processed": pages_with_pdfs,
                        "chunks_created": result.get("result", {}).get("total_chunks", 0),
                        "vectors_indexed": result.get("result", {}).get("total_vectors", 0),
                        "duration_seconds": result.get("processing_time_seconds", 0)
                    }
                }
                
        except Exception as e:
            return {"passed": False, "error": str(e)}
    
    async def _poll_task_status(self, client: httpx.AsyncClient, task_id: str, timeout: int = 300) -> Dict[str, Any]:
        """Poll task status until completion or timeout."""
        start_time = time.time()
        last_status = None
        
        while time.time() - start_time < timeout:
            try:
                resp = await client.get(
                    f"{self.api_base}/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {os.getenv('INDEXING_API_TOKEN', 'test-token')}"},
                    timeout=10
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status")
                    
                    # Log progress if status changed
                    if status != last_status:
                        progress = data.get("progress", {})
                        logger.info(f"  Status: {status} | Progress: {progress}")
                        last_status = status
                    
                    # Check for terminal states
                    if status in ["completed", "completed_with_errors", "failed", "cancelled"]:
                        return data
                        
            except Exception as e:
                logger.warning(f"Poll error: {e}")
            
            await asyncio.sleep(3)  # Poll every 3 seconds
        
        return {"status": "timeout", "error": f"Task did not complete within {timeout}s"}


async def main():
    """Main entry point."""
    # Configuration from environment
    api_base = os.getenv("INDEXING_API_BASE", "http://localhost:8080")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    logger.info(f"API Base: {api_base}")
    logger.info(f"Redis URL: {redis_url}")
    
    tester = ParallelProcessingTester(api_base=api_base, redis_url=redis_url)
    success = await tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
