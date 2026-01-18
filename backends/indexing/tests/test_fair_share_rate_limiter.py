"""
Comprehensive tests for Fair Share Rate Limiter.

Tests cover:
- Multiple concurrent jobs fair distribution
- Rate limit calculation
- Job session lifecycle
- Edge cases with single and many jobs
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from modules.embedder import FairShareRateLimiter, get_gemini_rate_limiter


class TestFairShareRateLimiterInit:
    """Tests for FairShareRateLimiter initialization."""

    def test_initialization_with_defaults(self):
        """
        Test initializing with default parameters.
        Real-world scenario: Default configuration for Gemini API.
        """
        limiter = FairShareRateLimiter()

        assert limiter.total_rate_limit == 120
        assert limiter.time_period == 60.0
        assert limiter.min_rate_per_job == 10
        assert limiter._active_jobs == 0

    def test_initialization_with_custom_values(self):
        """
        Test initializing with custom rate limits.
        Real-world scenario: Paid API tier with higher limits.
        """
        limiter = FairShareRateLimiter(
            total_rate_limit=500,
            time_period=60.0,
            min_rate_per_job=50
        )

        assert limiter.total_rate_limit == 500
        assert limiter.min_rate_per_job == 50


class TestFairShareRateLimiterCalculation:
    """Tests for rate calculation logic."""

    def test_rate_calculation_single_job(self):
        """
        Test rate for a single job.
        Real-world scenario: Only one indexing job running.
        """
        limiter = FairShareRateLimiter(total_rate_limit=120)
        limiter._active_jobs = 1

        rate = limiter._calculate_job_rate()

        assert rate == 120  # Full rate for single job

    def test_rate_calculation_two_jobs(self):
        """
        Test fair split between two jobs.
        Real-world scenario: Two customers indexing simultaneously.
        """
        limiter = FairShareRateLimiter(total_rate_limit=120)
        limiter._active_jobs = 2

        rate = limiter._calculate_job_rate()

        assert rate == 60  # 120 / 2

    def test_rate_calculation_many_jobs(self):
        """
        Test rate with many concurrent jobs.
        Real-world scenario: Peak usage with multiple customers.
        """
        limiter = FairShareRateLimiter(total_rate_limit=120, min_rate_per_job=10)
        limiter._active_jobs = 20

        rate = limiter._calculate_job_rate()

        # 120 / 20 = 6, but min is 10
        assert rate == 10  # Enforces minimum

    def test_rate_calculation_zero_jobs(self):
        """
        Test rate when no jobs are active.
        Real-world scenario: System idle state.
        """
        limiter = FairShareRateLimiter(total_rate_limit=120)
        limiter._active_jobs = 0

        rate = limiter._calculate_job_rate()

        assert rate == 120  # Full rate when idle

    def test_minimum_rate_enforcement(self):
        """
        Test that minimum rate is always enforced.
        Real-world scenario: Prevent job starvation under heavy load.
        """
        limiter = FairShareRateLimiter(total_rate_limit=100, min_rate_per_job=20)
        limiter._active_jobs = 10  # 100/10 = 10, but min is 20

        rate = limiter._calculate_job_rate()

        assert rate == 20


class TestFairShareRateLimiterJobSession:
    """Tests for job session management."""

    @pytest.mark.asyncio
    async def test_job_session_increments_counter(self):
        """
        Test that job session properly increments active jobs.
        Real-world scenario: New indexing job starts.
        """
        limiter = FairShareRateLimiter()

        assert limiter._active_jobs == 0

        async with limiter.job_session("job-1"):
            assert limiter._active_jobs == 1

        assert limiter._active_jobs == 0

    @pytest.mark.asyncio
    async def test_multiple_job_sessions(self):
        """
        Test multiple concurrent job sessions.
        Real-world scenario: Multiple customers indexing at once.
        """
        limiter = FairShareRateLimiter()

        async def run_job(job_id):
            async with limiter.job_session(job_id):
                await asyncio.sleep(0.1)

        # Start 3 jobs concurrently
        await asyncio.gather(
            run_job("job-1"),
            run_job("job-2"),
            run_job("job-3")
        )

        # All jobs should be cleaned up
        assert limiter._active_jobs == 0
        assert len(limiter._job_limiters) == 0

    @pytest.mark.asyncio
    async def test_job_session_creates_dedicated_limiter(self):
        """
        Test that each job gets its own rate limiter.
        Real-world scenario: Isolated rate tracking per job.
        """
        limiter = FairShareRateLimiter()

        async with limiter.job_session("job-test") as job_limiter:
            assert job_limiter is not None
            assert "job-test" in limiter._job_limiters

    @pytest.mark.asyncio
    async def test_job_session_cleanup_on_error(self):
        """
        Test that job session cleans up even on error.
        Real-world scenario: Job crashes mid-processing.
        """
        limiter = FairShareRateLimiter()

        with pytest.raises(ValueError):
            async with limiter.job_session("error-job"):
                assert limiter._active_jobs == 1
                raise ValueError("Job failed")

        # Should still clean up
        assert limiter._active_jobs == 0
        assert "error-job" not in limiter._job_limiters


class TestFairShareRateLimiterAcquire:
    """Tests for the acquire method."""

    @pytest.mark.asyncio
    async def test_acquire_with_job_id(self):
        """
        Test acquire uses job-specific limiter.
        Real-world scenario: API call within a job context.
        """
        limiter = FairShareRateLimiter()

        async with limiter.job_session("job-acquire"):
            # Should not raise
            await limiter.acquire(job_id="job-acquire")

    @pytest.mark.asyncio
    async def test_acquire_without_job_id_fallback(self):
        """
        Test acquire falls back to calculated rate.
        Real-world scenario: Orphan API call without job context.
        """
        limiter = FairShareRateLimiter()

        # Should not raise - uses fallback
        await limiter.acquire()

    @pytest.mark.asyncio
    async def test_acquire_with_invalid_job_id(self):
        """
        Test acquire with non-existent job ID.
        Real-world scenario: Stale job reference.
        """
        limiter = FairShareRateLimiter()

        # Should fall back to global limiter
        await limiter.acquire(job_id="non-existent")


class TestGetGeminiRateLimiter:
    """Tests for the global rate limiter getter."""

    def test_get_gemini_rate_limiter_singleton(self):
        """
        Test that rate limiter is a singleton.
        Real-world scenario: All embedders share same limiter.
        """
        # Reset global state for test
        with patch('modules.embedder._gemini_rate_limiter', None):
            limiter1 = get_gemini_rate_limiter()
            limiter2 = get_gemini_rate_limiter()

            assert limiter1 is limiter2

    def test_get_gemini_rate_limiter_respects_env(self):
        """
        Test that limiter respects environment variables.
        Real-world scenario: Custom rate limit configuration.
        """
        with patch('modules.embedder._gemini_rate_limiter', None):
            with patch.dict('os.environ', {'GEMINI_RATE_LIMIT': '200'}):
                limiter = get_gemini_rate_limiter()

                assert limiter.total_rate_limit == 200


class TestFairShareRateLimiterConcurrency:
    """Tests for concurrent access scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_job_registration(self):
        """
        Test thread-safe job registration.
        Real-world scenario: Burst of indexing requests.
        """
        limiter = FairShareRateLimiter()
        job_count = 10

        async def start_job(job_id):
            async with limiter.job_session(job_id):
                await asyncio.sleep(0.05)

        # Start all jobs nearly simultaneously
        tasks = [start_job(f"concurrent-{i}") for i in range(job_count)]
        await asyncio.gather(*tasks)

        # All should be cleaned up
        assert limiter._active_jobs == 0

    @pytest.mark.asyncio
    async def test_fair_distribution_under_load(self):
        """
        Test that jobs get fair share under concurrent load.
        Real-world scenario: Multiple large indexing jobs.
        """
        limiter = FairShareRateLimiter(total_rate_limit=120, min_rate_per_job=15)

        rates_observed = []

        async def observe_rate(job_id):
            async with limiter.job_session(job_id) as job_limiter:
                # The rate is set when job starts
                # We observe the max_rate from the limiter
                rates_observed.append(job_limiter.max_rate)
                await asyncio.sleep(0.01)

        # Start 4 jobs - each should get ~30 req/min (120/4)
        await asyncio.gather(
            observe_rate("job-1"),
            observe_rate("job-2"),
            observe_rate("job-3"),
            observe_rate("job-4")
        )

        # Each job should have gotten a reasonable rate
        for rate in rates_observed:
            assert rate >= 15  # At least minimum
            assert rate <= 120  # At most total
