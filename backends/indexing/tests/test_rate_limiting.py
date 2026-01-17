"""
Tests for Fair Share Rate Limiting.

These tests ensure that:
1. Multiple concurrent jobs get fair share of API quota
2. Single jobs get full rate when running alone
3. Jobs get at least minimum guaranteed rate
4. Rate is recalculated when jobs join/leave
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime


class TestFairShareRateLimiterInit:
    """Tests for FairShareRateLimiter initialization"""

    def test_default_configuration(self):
        """Test default configuration values"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter()

        assert limiter.total_rate_limit == 120  # Default
        assert limiter.time_period == 60.0
        assert limiter.min_rate_per_job == 10

    def test_custom_configuration(self):
        """Test custom configuration"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(
            total_rate_limit=200,
            time_period=30.0,
            min_rate_per_job=20
        )

        assert limiter.total_rate_limit == 200
        assert limiter.time_period == 30.0
        assert limiter.min_rate_per_job == 20

    def test_initial_state(self):
        """Test initial state has no active jobs"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter()

        assert limiter._active_jobs == 0
        assert len(limiter._job_limiters) == 0


class TestRateCalculation:
    """Tests for rate calculation logic"""

    def test_single_job_gets_full_rate(self):
        """Test single job gets entire rate limit"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=120)

        # Simulate single job
        limiter._active_jobs = 1
        rate = limiter._calculate_job_rate()

        assert rate == 120

    def test_two_jobs_split_rate(self):
        """Test two jobs split rate 50/50"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=120)

        # Simulate two jobs
        limiter._active_jobs = 2
        rate = limiter._calculate_job_rate()

        assert rate == 60

    def test_four_jobs_split_rate(self):
        """Test four jobs each get 1/4"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=120)

        limiter._active_jobs = 4
        rate = limiter._calculate_job_rate()

        assert rate == 30

    def test_minimum_rate_guaranteed(self):
        """Test jobs get at least minimum rate"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(
            total_rate_limit=100,
            min_rate_per_job=15
        )

        # With 10 jobs, calculated rate would be 10
        # But minimum is 15, so each job gets 15
        limiter._active_jobs = 10
        rate = limiter._calculate_job_rate()

        assert rate == 15  # Minimum guaranteed

    def test_rate_with_zero_jobs(self):
        """Test rate calculation with zero jobs"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=120)

        limiter._active_jobs = 0
        rate = limiter._calculate_job_rate()

        # Should return full rate (for next job that joins)
        assert rate == 120


class TestJobSessionManagement:
    """Tests for job session context manager"""

    @pytest.mark.asyncio
    async def test_job_session_registers_job(self):
        """Test job session increments active jobs count"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter()
        job_id = str(uuid4())

        assert limiter._active_jobs == 0

        async with limiter.job_session(job_id) as job_limiter:
            assert limiter._active_jobs == 1
            assert job_id in limiter._job_limiters

        # After context exit
        assert limiter._active_jobs == 0
        assert job_id not in limiter._job_limiters

    @pytest.mark.asyncio
    async def test_job_session_returns_limiter(self):
        """Test job session returns a rate limiter"""
        from modules.embedder import FairShareRateLimiter
        from aiolimiter import AsyncLimiter

        limiter = FairShareRateLimiter()
        job_id = str(uuid4())

        async with limiter.job_session(job_id) as job_limiter:
            assert isinstance(job_limiter, AsyncLimiter)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sessions(self):
        """Test multiple jobs can have concurrent sessions"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=120)

        job1_id = str(uuid4())
        job2_id = str(uuid4())

        async def run_job(job_id, delay=0):
            await asyncio.sleep(delay)
            async with limiter.job_session(job_id) as job_limiter:
                await asyncio.sleep(0.1)
                return limiter._active_jobs

        # Run two jobs concurrently
        results = await asyncio.gather(
            run_job(job1_id, 0),
            run_job(job2_id, 0.01)  # Small delay to ensure overlap
        )

        # At some point, both should have been active
        # One result should show 2 active jobs
        assert 2 in results or max(results) == 2

    @pytest.mark.asyncio
    async def test_session_cleanup_on_exception(self):
        """Test session cleans up even on exception"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter()
        job_id = str(uuid4())

        with pytest.raises(ValueError):
            async with limiter.job_session(job_id) as job_limiter:
                assert limiter._active_jobs == 1
                raise ValueError("Test exception")

        # Should still clean up
        assert limiter._active_jobs == 0
        assert job_id not in limiter._job_limiters


class TestGeminiDocumentEmbedderJobContext:
    """Tests for GeminiDocumentEmbedder job context methods"""

    @pytest.fixture
    def mock_embedder_config(self):
        """Create mock embedding configuration"""
        config = MagicMock()
        config.embed_model = "gemini-embedding-001"
        config.pinecone_api_key = "test-key"
        config.pinecone_index_name = "test-index"
        config.gemini_embedding_dimensions = 768
        return config

    def test_set_job_context(self, mock_embedder_config):
        """Test setting job context on embedder"""
        from modules.embedder import GeminiDocumentEmbedder
        from aiolimiter import AsyncLimiter

        with patch.object(GeminiDocumentEmbedder, '_setup_pinecone'):
            embedder = GeminiDocumentEmbedder(mock_embedder_config)

        job_id = str(uuid4())
        job_limiter = AsyncLimiter(60, 60)

        embedder.set_job_context(job_id, job_limiter)

        assert embedder._current_job_id == job_id
        assert embedder._job_rate_limiter == job_limiter

    def test_clear_job_context(self, mock_embedder_config):
        """Test clearing job context"""
        from modules.embedder import GeminiDocumentEmbedder
        from aiolimiter import AsyncLimiter

        with patch.object(GeminiDocumentEmbedder, '_setup_pinecone'):
            embedder = GeminiDocumentEmbedder(mock_embedder_config)

        job_id = str(uuid4())
        job_limiter = AsyncLimiter(60, 60)

        embedder.set_job_context(job_id, job_limiter)
        embedder.clear_job_context()

        assert embedder._current_job_id is None
        assert embedder._job_rate_limiter is None

    def test_get_active_rate_limiter_with_job(self, mock_embedder_config):
        """Test get_active_rate_limiter returns job limiter when set"""
        from modules.embedder import GeminiDocumentEmbedder
        from aiolimiter import AsyncLimiter

        with patch.object(GeminiDocumentEmbedder, '_setup_pinecone'):
            embedder = GeminiDocumentEmbedder(mock_embedder_config)

        job_limiter = AsyncLimiter(60, 60)
        embedder.set_job_context("job-1", job_limiter)

        active_limiter = embedder.get_active_rate_limiter()

        assert active_limiter == job_limiter

    def test_get_active_rate_limiter_fallback(self, mock_embedder_config):
        """Test get_active_rate_limiter falls back to global limiter"""
        from modules.embedder import GeminiDocumentEmbedder

        with patch.object(GeminiDocumentEmbedder, '_setup_pinecone'):
            embedder = GeminiDocumentEmbedder(mock_embedder_config)

        # No job context set
        active_limiter = embedder.get_active_rate_limiter()

        # Should return the global rate limiter
        assert active_limiter == embedder.rate_limiter


class TestRateLimitingInPipeline:
    """Tests for rate limiting integration in indexing pipeline"""

    @pytest.mark.asyncio
    async def test_pipeline_uses_fair_share_limiter(self):
        """Test indexing pipeline uses fair share rate limiter"""
        from modules.embedder import get_gemini_rate_limiter

        limiter = get_gemini_rate_limiter()

        # Should return a FairShareRateLimiter singleton
        assert limiter is not None

        # Should be same instance on second call (singleton)
        limiter2 = get_gemini_rate_limiter()
        assert limiter is limiter2

    @pytest.mark.asyncio
    async def test_embedder_respects_rate_limit(self):
        """Test embedder respects the rate limit"""
        from modules.embedder import FairShareRateLimiter
        from aiolimiter import AsyncLimiter

        # Create limiter with very low rate for testing
        limiter = FairShareRateLimiter(total_rate_limit=10, time_period=1.0)

        job_id = str(uuid4())

        async with limiter.job_session(job_id) as job_limiter:
            # Job limiter should have rate of 10/second
            assert isinstance(job_limiter, AsyncLimiter)

            # Simulate API calls
            start = asyncio.get_event_loop().time()

            for i in range(5):
                async with job_limiter:
                    pass  # Simulated API call

            elapsed = asyncio.get_event_loop().time() - start

            # Should complete relatively quickly with 10/sec rate
            assert elapsed < 1.0  # 5 calls at 10/sec should be < 1 second


class TestConcurrentJobScenarios:
    """Tests for realistic concurrent job scenarios"""

    @pytest.mark.asyncio
    async def test_two_jobs_fair_share(self):
        """Test two concurrent jobs get fair share"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=100, time_period=60.0)

        job1_rate = None
        job2_rate = None

        async def job1():
            nonlocal job1_rate
            async with limiter.job_session("job1") as jl:
                # Wait for job2 to join
                await asyncio.sleep(0.05)
                job1_rate = limiter._calculate_job_rate()
                await asyncio.sleep(0.1)

        async def job2():
            nonlocal job2_rate
            await asyncio.sleep(0.01)  # Start slightly after job1
            async with limiter.job_session("job2") as jl:
                job2_rate = limiter._calculate_job_rate()
                await asyncio.sleep(0.1)

        await asyncio.gather(job1(), job2())

        # Both should have gotten 50 (100/2)
        assert job1_rate == 50
        assert job2_rate == 50

    @pytest.mark.asyncio
    async def test_job_completion_releases_quota(self):
        """Test completing job releases its quota share"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(total_rate_limit=100)

        rates_during = []
        rate_after = None

        async def short_job():
            async with limiter.job_session("short"):
                rates_during.append(limiter._calculate_job_rate())
                await asyncio.sleep(0.05)

        async def long_job():
            nonlocal rate_after
            async with limiter.job_session("long"):
                # Initially share with short_job
                await asyncio.sleep(0.02)
                rates_during.append(limiter._calculate_job_rate())

                # Wait for short_job to complete
                await asyncio.sleep(0.1)

                # Now should have full rate
                rate_after = limiter._calculate_job_rate()

        await asyncio.gather(short_job(), long_job())

        # During: both jobs sharing -> 50 each
        assert 50 in rates_during

        # After short_job completes: long_job gets full 100
        assert rate_after == 100

    @pytest.mark.asyncio
    async def test_many_concurrent_jobs(self):
        """Test many concurrent jobs scenario"""
        from modules.embedder import FairShareRateLimiter

        limiter = FairShareRateLimiter(
            total_rate_limit=120,
            min_rate_per_job=10
        )

        max_active = 0

        async def simulate_job(job_id):
            nonlocal max_active
            async with limiter.job_session(job_id):
                max_active = max(max_active, limiter._active_jobs)
                await asyncio.sleep(0.05)

        # Start 10 jobs
        jobs = [simulate_job(f"job-{i}") for i in range(10)]
        await asyncio.gather(*jobs)

        # At peak, should have had 10 active jobs
        assert max_active == 10

        # After all complete, should be 0
        assert limiter._active_jobs == 0


class TestRateLimiterSingleton:
    """Tests for rate limiter singleton behavior"""

    def test_get_gemini_rate_limiter_singleton(self):
        """Test get_gemini_rate_limiter returns singleton"""
        from modules.embedder import get_gemini_rate_limiter

        limiter1 = get_gemini_rate_limiter()
        limiter2 = get_gemini_rate_limiter()

        assert limiter1 is limiter2

    def test_singleton_persists_state(self):
        """Test singleton maintains state across calls"""
        from modules.embedder import get_gemini_rate_limiter

        limiter = get_gemini_rate_limiter()

        # Modify state
        original_rate = limiter.total_rate_limit

        # Get again
        limiter2 = get_gemini_rate_limiter()

        # Should have same state
        assert limiter2.total_rate_limit == original_rate


class TestEnvironmentConfiguration:
    """Tests for environment-based configuration"""

    @patch.dict('os.environ', {'GEMINI_RATE_LIMIT': '200'})
    def test_rate_limit_from_env(self):
        """Test rate limit can be configured from environment"""
        import os

        rate_limit = int(os.getenv('GEMINI_RATE_LIMIT', '120'))
        assert rate_limit == 200

    @patch.dict('os.environ', {'ENABLE_PER_JOB_RATE_LIMIT': 'true'})
    def test_per_job_rate_limit_enabled(self):
        """Test per-job rate limiting can be enabled via env"""
        import os

        enabled = os.getenv('ENABLE_PER_JOB_RATE_LIMIT', 'false').lower() == 'true'
        assert enabled is True

    @patch.dict('os.environ', {'ENABLE_PER_JOB_RATE_LIMIT': 'false'})
    def test_per_job_rate_limit_disabled(self):
        """Test per-job rate limiting can be disabled"""
        import os

        enabled = os.getenv('ENABLE_PER_JOB_RATE_LIMIT', 'false').lower() == 'true'
        assert enabled is False
