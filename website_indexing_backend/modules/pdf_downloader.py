"""
Production-grade PDF downloader module for in-memory PDF processing.
Implements async downloading with retry logic, connection pooling, streaming,
and circuit breaker pattern for robust PDF handling.
"""

import asyncio
import logging
import os
import ssl
import time
import hashlib
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, List
from urllib.parse import urlparse, unquote
from enum import Enum

import aiohttp
from aiohttp import ClientTimeout, TCPConnector

# Fix for macOS SSL certificate verification
# On macOS, Python's ssl module may not find system CA certificates
# certifi provides a reliable set of root certificates
try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False

logger = logging.getLogger(__name__)


class PDFDownloadError(Exception):
    """Base exception for PDF download errors."""
    pass


class PDFSizeExceededError(PDFDownloadError):
    """Raised when PDF exceeds maximum size limit."""
    pass


class PDFNotFoundError(PDFDownloadError):
    """Raised when PDF URL returns 404."""
    pass


class PDFContentTypeError(PDFDownloadError):
    """Raised when URL does not return PDF content."""
    pass


class PDFTimeoutError(PDFDownloadError):
    """Raised when PDF download times out."""
    pass


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class PDFDownloadConfig:
    """Configuration for PDF downloading."""
    # Timeouts
    connect_timeout: int = 10  # Connection timeout in seconds
    read_timeout: int = 120    # Read timeout for large PDFs
    total_timeout: int = 180   # Total request timeout

    # Retry settings
    max_retries: int = 3
    retry_base_delay: float = 1.0  # Base delay for exponential backoff
    retry_max_delay: float = 30.0  # Maximum delay between retries
    retry_multiplier: float = 2.0  # Exponential backoff multiplier

    # Size limits
    max_size_mb: int = 100  # Maximum PDF size in MB
    streaming_threshold_mb: int = 10  # Use streaming for files larger than this
    chunk_size: int = 64 * 1024  # 64KB chunks for streaming

    # Connection pooling
    connection_limit: int = 10  # Max concurrent connections
    connection_limit_per_host: int = 5  # Max connections per host
    keepalive_timeout: int = 30  # Keep connections alive

    # Circuit breaker
    circuit_failure_threshold: int = 5  # Failures before opening circuit
    circuit_recovery_timeout: int = 60  # Seconds before trying again

    # SSL
    verify_ssl: bool = True

    # User agent
    user_agent: str = "Mozilla/5.0 (compatible; WebBotify/1.0; +https://webbotify.com/bot)"


@dataclass
class PDFDownloadResult:
    """Result of a PDF download operation."""
    success: bool
    url: str
    content: Optional[bytes] = None
    content_type: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: int = 0
    download_time: float = 0.0
    retries_used: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/metrics."""
        return {
            "success": self.success,
            "url": self.url,
            "size_bytes": self.size_bytes,
            "download_time": self.download_time,
            "retries_used": self.retries_used,
            "error": self.error,
            "error_type": self.error_type,
            "filename": self.filename,
        }


@dataclass
class CircuitBreaker:
    """Simple circuit breaker implementation for failing hosts."""
    failure_count: int = 0
    last_failure_time: float = 0
    state: CircuitState = CircuitState.CLOSED
    failure_threshold: int = 5
    recovery_timeout: int = 60

    def record_failure(self):
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def record_success(self):
        """Record a success and reset the circuit."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def can_execute(self) -> bool:
        """Check if requests are allowed through the circuit."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN state allows one request through
        return True


class PDFDownloader:
    """
    Production-grade async PDF downloader with:
    - Connection pooling for efficiency
    - Retry logic with exponential backoff
    - Streaming downloads for large files
    - Circuit breaker pattern for failing hosts
    - In-memory processing (no disk storage required)
    """

    def __init__(self, config: Optional[PDFDownloadConfig] = None):
        self.config = config or PDFDownloadConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

        # Statistics
        self.stats = {
            "total_downloads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "total_bytes_downloaded": 0,
            "total_download_time": 0.0,
            "retries_used": 0,
            "circuit_breaker_rejections": 0,
        }

        # Load config from environment if available
        self._load_env_config()

    def _load_env_config(self):
        """Override config from environment variables."""
        if os.getenv("MAX_PDF_SIZE_MB"):
            self.config.max_size_mb = int(os.getenv("MAX_PDF_SIZE_MB"))
        if os.getenv("PDF_CONNECT_TIMEOUT"):
            self.config.connect_timeout = int(os.getenv("PDF_CONNECT_TIMEOUT"))
        if os.getenv("PDF_READ_TIMEOUT"):
            self.config.read_timeout = int(os.getenv("PDF_READ_TIMEOUT"))
        if os.getenv("PDF_MAX_RETRIES"):
            self.config.max_retries = int(os.getenv("PDF_MAX_RETRIES"))
        if os.getenv("SSL_VERIFY"):
            self.config.verify_ssl = os.getenv("SSL_VERIFY", "true").lower() == "true"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            # Configure SSL context
            if self.config.verify_ssl:
                # Use certifi CA certificates if available (fixes macOS SSL issues)
                if CERTIFI_AVAILABLE:
                    ssl_context = ssl.create_default_context(cafile=certifi.where())
                else:
                    ssl_context = ssl.create_default_context()
            else:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            # Create connector with pooling
            connector = TCPConnector(
                limit=self.config.connection_limit,
                limit_per_host=self.config.connection_limit_per_host,
                keepalive_timeout=self.config.keepalive_timeout,
                ssl=ssl_context,
                enable_cleanup_closed=True,
            )

            # Create timeout configuration
            timeout = ClientTimeout(
                total=self.config.total_timeout,
                connect=self.config.connect_timeout,
                sock_read=self.config.read_timeout,
            )

            # Create session with headers
            headers = {
                "User-Agent": self.config.user_agent,
                "Accept": "application/pdf,*/*",
            }

            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=headers,
            )

        return self._session

    def _get_circuit_breaker(self, host: str) -> CircuitBreaker:
        """Get or create circuit breaker for a host."""
        if host not in self._circuit_breakers:
            self._circuit_breakers[host] = CircuitBreaker(
                failure_threshold=self.config.circuit_failure_threshold,
                recovery_timeout=self.config.circuit_recovery_timeout,
            )
        return self._circuit_breakers[host]

    @staticmethod
    def is_pdf_url(url: str) -> bool:
        """
        Check if a URL likely points to a PDF file.
        Uses URL extension check as a heuristic.
        """
        url_lower = url.lower().split('?')[0].split('#')[0]
        return url_lower.endswith('.pdf')

    @staticmethod
    def is_pdf_content_type(content_type: Optional[str]) -> bool:
        """Check if Content-Type indicates a PDF."""
        if not content_type:
            return False
        return 'application/pdf' in content_type.lower()

    @staticmethod
    def extract_filename_from_url(url: str) -> Optional[str]:
        """Extract filename from URL path."""
        try:
            parsed = urlparse(url)
            path = unquote(parsed.path)
            if path:
                filename = path.split('/')[-1]
                if filename:
                    return filename
        except Exception:
            pass
        return None

    @staticmethod
    def extract_filename_from_header(content_disposition: Optional[str]) -> Optional[str]:
        """Extract filename from Content-Disposition header."""
        if not content_disposition:
            return None
        try:
            # Parse Content-Disposition: attachment; filename="document.pdf"
            parts = content_disposition.split(';')
            for part in parts:
                part = part.strip()
                if part.lower().startswith('filename='):
                    filename = part[9:].strip('"\'')
                    return unquote(filename)
                if part.lower().startswith('filename*='):
                    # Handle RFC 5987 encoded filenames
                    value = part[10:]
                    if "''" in value:
                        # Format: charset'language'encoded_filename
                        filename = value.split("''", 1)[-1]
                        return unquote(filename)
        except Exception:
            pass
        return None

    async def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self.config.retry_base_delay * (self.config.retry_multiplier ** attempt)
        # Add jitter to prevent thundering herd
        import random
        jitter = random.uniform(0, delay * 0.1)
        return min(delay + jitter, self.config.retry_max_delay)

    async def download_pdf(self, url: str) -> PDFDownloadResult:
        """
        Download a PDF from a URL into memory.

        Args:
            url: The URL to download from

        Returns:
            PDFDownloadResult with the downloaded content or error info
        """
        start_time = time.time()
        self.stats["total_downloads"] += 1

        # Parse URL for host-based circuit breaker
        parsed = urlparse(url)
        host = parsed.netloc
        circuit = self._get_circuit_breaker(host)

        # Check circuit breaker
        if not circuit.can_execute():
            self.stats["circuit_breaker_rejections"] += 1
            self.stats["failed_downloads"] += 1
            return PDFDownloadResult(
                success=False,
                url=url,
                error=f"Circuit breaker open for host {host}",
                error_type="circuit_breaker",
            )

        last_error: Optional[str] = None
        last_error_type: Optional[str] = None
        retries_used = 0

        for attempt in range(self.config.max_retries + 1):
            try:
                result = await self._attempt_download(url)

                # Record success
                circuit.record_success()
                self.stats["successful_downloads"] += 1
                self.stats["total_bytes_downloaded"] += result.size_bytes
                self.stats["retries_used"] += retries_used

                result.download_time = time.time() - start_time
                result.retries_used = retries_used

                logger.info(
                    f"Successfully downloaded PDF: {url} "
                    f"({result.size_bytes / 1024:.1f}KB in {result.download_time:.2f}s, "
                    f"retries: {retries_used})"
                )

                return result

            except PDFNotFoundError as e:
                # Don't retry 404s
                circuit.record_failure()
                self.stats["failed_downloads"] += 1
                return PDFDownloadResult(
                    success=False,
                    url=url,
                    error=str(e),
                    error_type="not_found",
                    download_time=time.time() - start_time,
                )

            except PDFSizeExceededError as e:
                # Don't retry size errors
                self.stats["failed_downloads"] += 1
                return PDFDownloadResult(
                    success=False,
                    url=url,
                    error=str(e),
                    error_type="size_exceeded",
                    download_time=time.time() - start_time,
                )

            except PDFContentTypeError as e:
                # Don't retry content type errors
                self.stats["failed_downloads"] += 1
                return PDFDownloadResult(
                    success=False,
                    url=url,
                    error=str(e),
                    error_type="content_type",
                    download_time=time.time() - start_time,
                )

            except (PDFTimeoutError, PDFDownloadError, aiohttp.ClientError) as e:
                last_error = str(e)
                last_error_type = "download_error"
                retries_used = attempt + 1

                if attempt < self.config.max_retries:
                    delay = await self._calculate_backoff(attempt)
                    logger.warning(
                        f"PDF download attempt {attempt + 1} failed for {url}: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"PDF download failed after {self.config.max_retries + 1} attempts: {url}")

            except Exception as e:
                last_error = str(e)
                last_error_type = "unexpected_error"
                logger.error(f"Unexpected error downloading PDF {url}: {e}")
                break

        # All retries exhausted
        circuit.record_failure()
        self.stats["failed_downloads"] += 1
        self.stats["retries_used"] += retries_used

        return PDFDownloadResult(
            success=False,
            url=url,
            error=last_error,
            error_type=last_error_type,
            download_time=time.time() - start_time,
            retries_used=retries_used,
        )

    async def _attempt_download(self, url: str) -> PDFDownloadResult:
        """Single download attempt."""
        session = await self._get_session()

        async with session.get(url, allow_redirects=True) as response:
            # Check HTTP status
            if response.status == 404:
                raise PDFNotFoundError(f"PDF not found: HTTP 404")

            if response.status != 200:
                raise PDFDownloadError(f"HTTP {response.status}")

            # Get content info
            content_type = response.headers.get('Content-Type', '')
            content_disposition = response.headers.get('Content-Disposition', '')
            content_length = response.headers.get('Content-Length')

            # Extract filename
            filename = (
                self.extract_filename_from_header(content_disposition) or
                self.extract_filename_from_url(url)
            )

            # Verify it's a PDF (by content-type or URL extension)
            is_pdf = (
                self.is_pdf_content_type(content_type) or
                self.is_pdf_url(url) or
                (filename and filename.lower().endswith('.pdf'))
            )

            if not is_pdf:
                raise PDFContentTypeError(
                    f"URL does not appear to be a PDF (Content-Type: {content_type})"
                )

            # Check size limit from Content-Length header
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > self.config.max_size_mb:
                    raise PDFSizeExceededError(
                        f"PDF size ({size_mb:.1f}MB) exceeds limit ({self.config.max_size_mb}MB)"
                    )

            # Download content
            content_length_int = int(content_length) if content_length else 0
            use_streaming = content_length_int > (self.config.streaming_threshold_mb * 1024 * 1024)

            if use_streaming:
                # Streaming download for large files
                content = await self._stream_download(response)
            else:
                # Regular download for smaller files
                content = await response.read()

            # Verify final size
            size_bytes = len(content)
            size_mb = size_bytes / (1024 * 1024)
            if size_mb > self.config.max_size_mb:
                raise PDFSizeExceededError(
                    f"PDF size ({size_mb:.1f}MB) exceeds limit ({self.config.max_size_mb}MB)"
                )

            # Verify PDF magic bytes
            if not content.startswith(b'%PDF'):
                raise PDFContentTypeError("File does not appear to be a valid PDF (missing magic bytes)")

            return PDFDownloadResult(
                success=True,
                url=url,
                content=content,
                content_type=content_type,
                filename=filename,
                size_bytes=size_bytes,
            )

    async def _stream_download(self, response: aiohttp.ClientResponse) -> bytes:
        """Stream download for large files with progress tracking."""
        chunks = []
        total_size = 0
        max_size = self.config.max_size_mb * 1024 * 1024

        async for chunk in response.content.iter_chunked(self.config.chunk_size):
            total_size += len(chunk)

            # Check size during download
            if total_size > max_size:
                raise PDFSizeExceededError(
                    f"PDF exceeds size limit during download ({total_size / 1024 / 1024:.1f}MB)"
                )

            chunks.append(chunk)

        return b''.join(chunks)

    async def download_multiple(
        self,
        urls: List[str],
        max_concurrency: int = 5
    ) -> List[PDFDownloadResult]:
        """
        Download multiple PDFs concurrently with controlled concurrency.

        Args:
            urls: List of PDF URLs to download
            max_concurrency: Maximum concurrent downloads

        Returns:
            List of PDFDownloadResult objects
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def download_with_semaphore(url: str) -> PDFDownloadResult:
            async with semaphore:
                return await self.download_pdf(url)

        tasks = [download_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks)

    async def close(self):
        """Close the aiohttp session and cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def get_stats(self) -> Dict[str, Any]:
        """Get download statistics."""
        stats = self.stats.copy()
        if stats["total_downloads"] > 0:
            stats["success_rate"] = stats["successful_downloads"] / stats["total_downloads"]
            stats["avg_download_time"] = (
                stats["total_download_time"] / stats["successful_downloads"]
                if stats["successful_downloads"] > 0 else 0
            )
        return stats

    def reset_stats(self):
        """Reset download statistics."""
        self.stats = {
            "total_downloads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "total_bytes_downloaded": 0,
            "total_download_time": 0.0,
            "retries_used": 0,
            "circuit_breaker_rejections": 0,
        }

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
