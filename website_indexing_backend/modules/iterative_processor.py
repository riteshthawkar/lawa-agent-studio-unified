"""
Iterative processor module using Crawl4AI for enhanced content processing.
Second phase: Process each collected URL (cleaning → embedding → indexing).
Enhanced with better JavaScript support and content extraction.
"""

import asyncio
import logging
import hashlib
import re
import psutil
import os
import aiohttp
import ssl
from typing import List, Dict, Any, Optional, Tuple, Callable, Awaitable
from pathlib import Path
import fitz # PyMuPDF for quick page count check

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.content_scraping_strategy import WebScrapingStrategy  # Use Pruning Strategy for fresh fetches

from .embedder import DocumentEmbedder, GeminiDocumentEmbedder
from .config import EmbeddingConfig, PreprocessorConfig, PDFConfig, ProcessingConfig
from .content_preprocessor import ContentPreprocessor
from .pdf_processor import PDFProcessor, worker_process_pdf_from_bytes
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from .pdf_downloader import PDFDownloader, PDFDownloadConfig, PDFDownloadResult

logger = logging.getLogger(__name__)

# Add file handler for debugging
import os
log_file = os.path.join(os.path.dirname(__file__), '..', 'debug.log')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class IterativeProcessor:
    """
    Processes URLs using Crawl4AI: enhanced content extraction → embedding → indexing.
    This is the second phase after URL collection.
    """
    
    def __init__(
        self,
        embedding_config: EmbeddingConfig,
        preloaded_embedder=None,
        preprocessor_config: PreprocessorConfig = None,
        pdf_config: PDFConfig = None,
        db_manager=None,
        task_id=None,
        progress_callback: Optional[Callable[[str, int, int, int], Awaitable[None]]] = None
    ):
        self.embedding_config = embedding_config
        self.db_manager = db_manager
        self.task_id = task_id
        self.progress_callback = progress_callback

        # Use pre-loaded embedder if available, otherwise create new one
        if preloaded_embedder:
            self.embedder = preloaded_embedder
            logger.info("Using pre-loaded embedder")
        else:
            # Choose embedder based on model type
            if embedding_config.embed_model.startswith("gemini"):
                self.embedder = GeminiDocumentEmbedder(embedding_config)
                logger.info("Creating new Gemini embedder instance")
            else:
                self.embedder = DocumentEmbedder(embedding_config)
                logger.info("Creating new local embedder instance")

        # Initialize content preprocessor (enabled by default)
        self.preprocessor_config = preprocessor_config or PreprocessorConfig()
        self.preprocessor = ContentPreprocessor(self.preprocessor_config)
        logger.info("Content preprocessor initialized")

        # Initialize PDF processor (disabled by default, OCR disabled by default)
        self.pdf_config = pdf_config or PDFConfig()

        if self.pdf_config.enabled:
            # Create a ProcessingConfig to pass to PDFProcessor
            # This ensures PDFProcessor receives the configuration object it expects
            proc_config = ProcessingConfig(pdf_enabled=True)
            self.pdf_processor = PDFProcessor(proc_config)

            # Initialize production-grade PDF downloader with connection pooling
            # Uses configuration from PDFConfig dataclass
            pdf_download_config = PDFDownloadConfig(
                max_size_mb=self.pdf_config.max_size_mb,
                max_retries=self.pdf_config.max_retries,
                connect_timeout=10,
                read_timeout=self.pdf_config.download_timeout,
                total_timeout=self.pdf_config.download_timeout + 60,  # Add buffer
                streaming_threshold_mb=self.pdf_config.streaming_threshold_mb,
            )
            self.pdf_downloader = PDFDownloader(pdf_download_config)
            logger.info(f"PDF processor initialized (OCR enabled: {self.pdf_config.ocr_enabled})")
            logger.info(f"PDF downloader initialized (max_size: {self.pdf_config.max_size_mb}MB, "
                       f"timeout: {self.pdf_config.download_timeout}s, retries: {self.pdf_config.max_retries})")
        else:
            self.pdf_processor = None
            self.pdf_downloader = None

        # Processing stats
        self.stats = {
            "urls_processed": 0,
            "urls_successful": 0,
            "urls_failed": 0,
            "documents_indexed": 0,
            "errors": 0,
            "start_time": None,
            "duration": None,
            "preprocessing_stats": {
                "total_reduction_bytes": 0,
                "urls_preprocessed": 0
            },
            "pdf_stats": {
                "pdfs_detected": 0,
                "pdfs_processed": 0,
                "pdfs_failed": 0
            }
        }

        # Per-URL tracking for visibility (Bug #26 fix: per-URL status reporting)
        self.url_results: List[Dict[str, Any]] = []

        logger.info("IterativeProcessor initialized with Crawl4AI and content preprocessing")

        # Memory management
        self.max_memory_mb = int(os.getenv("MAX_MEMORY_MB", "2048"))  # 2GB default
        self.memory_check_interval = 10  # Check every 10 URLs

        # Process Pool for CPU-intensive PDF tasks - DISABLED in daemon processes (Celery workers)
        # Celery workers are daemon processes and cannot spawn sub-processes (ProcessPoolExecutor)
        # This causes: "daemonic processes are not allowed to have children"
        # Solution: Use ThreadPoolExecutor for PDF processing instead
        # Note: PyMuPDF releases the GIL during PDF operations, so threading is still efficient
        max_workers = max(1, (os.cpu_count() or 2) // 2)
        # self.process_pool = ProcessPoolExecutor(max_workers=max_workers)  # Disabled - can't use in Celery
        self.process_pool = None  # Disabled for Celery compatibility
        logger.info(f"ProcessPoolExecutor disabled for Celery compatibility (daemon process limitation)")
        
        # Thread Pool for CPU-bound but GIL-releasing tasks (like markdown splitting AND PDF processing)
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers + 4)
        logger.info(f"Initialized ThreadPoolExecutor with {max_workers + 4} workers for chunking and PDF tasks")

    async def close(self):
        """Cleanup resources - shutdown executor pools."""
        try:
            # self.process_pool.shutdown(wait=False)  # Disabled - using ThreadPool only
            self.thread_pool.shutdown(wait=False)
            logger.info("Successfully shutdown ThreadPoolExecutor")
        except Exception as e:
            logger.warning(f"Error shutting down executors: {e}")

    def _extract_title_from_content(self, content: str, html_content: str = None) -> str:
        """Extract title from content.

        Args:
            content: Markdown or text content
            html_content: Optional HTML content for better title extraction
        """
        try:
            # First try HTML title if available (most reliable)
            if html_content:
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = title_match.group(1).strip()
                    title = re.sub(r'\s+', ' ', title)
                    if title and title.lower() not in ('untitled', 'document', ''):
                        return title[:200]

            # Try HTML title in content
            title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                if title and title.lower() not in ('untitled', 'document', ''):
                    return title[:200]

            # Look for markdown title (first h1)
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
                if title and title.lower() not in ('untitled', 'document', ''):
                    return title[:200]

            # Look for first non-empty line as potential title
            for line in content.split('\n')[:10]:
                line = line.strip()
                # Skip markdown formatting, links, and short lines
                if line and not line.startswith(('#', '[', '!', '-', '*', '>', '`')) and len(line) > 5 and len(line) < 150:
                    return line[:200]

            return "Untitled"
        except Exception:
            return "Untitled"

    def _record_url_result(
        self,
        url: str,
        status: str,
        content_type: str = "html",
        document_count: int = 0,
        content_size_bytes: int = 0,
        title: str = "",
        error_message: str = ""
    ) -> None:
        """
        Record per-URL processing result for visibility reporting.
        Bug #26 fix: Track individual URL status for Django backend.

        Args:
            url: The processed URL
            status: One of 'indexed', 'failed', 'skipped'
            content_type: 'html', 'pdf', or 'other'
            document_count: Number of chunks/documents created
            content_size_bytes: Size of extracted content
            title: Extracted page title
            error_message: Error message if failed
        """
        self.url_results.append({
            "url": url,
            "status": status,
            "content_type": content_type,
            "document_count": document_count,
            "content_size_bytes": content_size_bytes,
            "title": title[:500] if title else "",
            "error_message": error_message[:1000] if error_message else ""
        })

    def _is_pdf_url(self, url: str, content_type: str = None) -> bool:
        """
        Detect if a URL points to a PDF file.
        Uses multiple heuristics: URL extension, Content-Type, and URL patterns.

        Args:
            url: The URL to check
            content_type: Optional Content-Type header value

        Returns:
            True if the URL is a PDF, False otherwise
        """
        # Check URL extension (remove query params and fragments)
        url_lower = url.lower().split('?')[0].split('#')[0]
        if url_lower.endswith('.pdf'):
            return True

        # Check Content-Type header if provided
        if content_type and 'application/pdf' in content_type.lower():
            return True

        # Check for common PDF download patterns in URL
        # Bug fix: Enhanced detection for dynamic PDF URLs
        url_lower_full = url.lower()
        pdf_patterns = [
            '/download/pdf/',
            '/pdf/download/',
            '/export/pdf',
            '/generate-pdf',
            '/get-pdf',
            '/getpdf',
            '/view-pdf',
            '/render/pdf',
            'format=pdf',
            'type=pdf',
            'output=pdf',
            'filetype=pdf',
            '&pdf=',
            '?pdf=',
            '/pdf/',
            '.pdf?',  # PDF with query params
            # Production Enhancement: Handle dynamic extensions that often serve PDFs
            'download.ashx',
            'handler.ashx',
            'getfile.ashx',
            'document.ashx',
            'file.ashx',
            'attachment.ashx',
            'getdocument.aspx',
            'downloadfile.aspx',
        ]
        for pattern in pdf_patterns:
            if pattern in url_lower_full:
                return True

        return False
    
    # Dynamic extensions that may serve HTML or PDF - need Content-Type check
    DYNAMIC_EXTENSIONS = ['.ashx', '.aspx', '.php', '.jsp', '.cfm', '.do', '.action']
    
    def _needs_content_type_check(self, url: str) -> bool:
        """
        Check if URL has dynamic extension that could serve any content type.
        These URLs don't have file extensions that indicate content type, so we 
        need to check Content-Type header to determine how to process them.
        
        Args:
            url: The URL to check
            
        Returns:
            True if the URL has a dynamic extension that needs Content-Type checking
        """
        url_lower = url.lower().split('?')[0].split('#')[0]
        return any(url_lower.endswith(ext) for ext in self.DYNAMIC_EXTENSIONS)

    async def _fetch_pdf_bytes(self, url: str, timeout: int = 120) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Fetch PDF content as bytes from a URL using production-grade downloader.

        Args:
            url: The URL to fetch
            timeout: Request timeout in seconds (now handled by PDFDownloader)

        Returns:
            Tuple of (pdf_bytes, content_type) or (None, None) on failure
        """
        if not self.pdf_downloader:
            logger.warning("PDF downloader not initialized")
            return None, None

        try:
            # Use the production-grade PDF downloader with retry logic,
            # connection pooling, and circuit breaker pattern
            result: PDFDownloadResult = await self.pdf_downloader.download_pdf(url)

            if result.success and result.content:
                logger.info(
                    f"Fetched PDF from {url}: {result.size_bytes / 1024:.1f}KB "
                    f"in {result.download_time:.2f}s (retries: {result.retries_used})"
                )
                return result.content, result.content_type
            else:
                logger.warning(
                    f"Failed to fetch PDF from {url}: {result.error} "
                    f"(type: {result.error_type})"
                )
                return None, None

        except Exception as e:
            logger.error(f"Unexpected error fetching PDF from {url}: {e}")
            return None, None

    async def _process_pdf_url(self, url: str, namespace: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process a PDF URL: fetch → extract text → chunk → embed → index.
        Uses production-grade in-memory processing with no disk storage required.

        Args:
            url: The PDF URL to process
            namespace: Pinecone namespace for indexing

        Returns:
            Processed document dictionary or None on failure
        """
        if not self.pdf_processor:
            logger.warning(f"PDF processing disabled, skipping {url}")
            return None

        self.stats["pdf_stats"]["pdfs_detected"] += 1

        try:
            # Fetch PDF bytes using production-grade downloader
            # (handles retries, connection pooling, circuit breaker)
            pdf_bytes, content_type = await self._fetch_pdf_bytes(url)
            if not pdf_bytes:
                self.stats["pdf_stats"]["pdfs_failed"] += 1
                # Record failed URL result
                self._record_url_result(
                    url=url,
                    status="failed",
                    content_type="pdf",
                    error_message="Failed to download PDF"
                )
                return None

            # Process PDF in CHUNKS to prevent blocking and memory spikes
            # 1. Get total page count first (lightweight)
            try:
                doc_check = fitz.open(stream=pdf_bytes, filetype="pdf")
                total_possible_pages = len(doc_check)
                doc_check.close()
            except Exception:
                total_possible_pages = 100 # Fallback
            
            # 2. Determine processing limits
            # If max_pages is None, process everything. Otherwise min(total, max_pages)
            max_limit = self.pdf_config.max_pages if self.pdf_config.max_pages else total_possible_pages
            final_end_page = min(total_possible_pages, max_limit)
            
            CHUNK_SIZE = 20
            all_markdown_parts = []
            
            logger.info(f"Starting PDF processing for {url}: {final_end_page} pages in chunks of {CHUNK_SIZE}")

            loop = asyncio.get_running_loop()
            
            for start_page in range(0, final_end_page, CHUNK_SIZE):
                end_page = min(start_page + CHUNK_SIZE, final_end_page)
                
                logger.info(f"Processing PDF chunk {start_page}-{end_page} for {url}")
                
                # Submit chunk to thread pool (not process pool - Celery workers are daemons)
                # PyMuPDF releases the GIL during PDF operations, so threading is still efficient
                chunk_markdown = await loop.run_in_executor(
                    self.thread_pool,  # Using thread pool for Celery compatibility
                    worker_process_pdf_from_bytes,
                    pdf_bytes,
                    url,
                    os.getenv("GEMINI_API_KEY"),
                    start_page,  # start_page
                    end_page,    # end_page
                    1024,        # memory_limit_mb
                    True         # auto_ocr
                )
                
                if chunk_markdown:
                    all_markdown_parts.append(chunk_markdown)
                
                # Yield control to event loop to allow other tasks (like heartbeats/status queries) to run
                await asyncio.sleep(0.1)

            # Join all parts
            markdown_content = "\n\n".join(all_markdown_parts)

            # Free PDF bytes from memory after extraction
            del pdf_bytes

            if not markdown_content or len(markdown_content) < 50:
                logger.warning(f"No meaningful content extracted from PDF: {url}")
                self.stats["pdf_stats"]["pdfs_failed"] += 1
                # Record skipped URL result
                self._record_url_result(
                    url=url,
                    status="skipped",
                    content_type="pdf",
                    error_message="No meaningful content extracted"
                )
                return None

            original_size_kb = len(markdown_content.encode('utf-8')) / 1024
            logger.info(f"Extracted {len(markdown_content)} chars ({original_size_kb:.1f}KB) from PDF: {url}")

            # Store original content BEFORE preprocessing for citations (Bug #23-24 fix)
            original_content = markdown_content

            # Apply content preprocessing (same as HTML)
            # This tokenizes URLs/media for cleaner embeddings
            markdown_content, preprocess_metadata = self.preprocessor.process(
                markdown_content, content_type="markdown"
            )

            # Update preprocessing stats
            self.stats["preprocessing_stats"]["urls_preprocessed"] += 1
            if "processed_length" in preprocess_metadata:
                reduction = preprocess_metadata.get("original_length", 0) - preprocess_metadata.get("processed_length", 0)
                self.stats["preprocessing_stats"]["total_reduction_bytes"] += reduction

            processed_size_kb = len(markdown_content.encode('utf-8')) / 1024
            logger.info(f"Preprocessed PDF content: {processed_size_kb:.1f}KB "
                       f"(reduced {preprocess_metadata.get('reduction_percent', 0)}%)")

            # Extract URLs and media from preprocessing metadata (Bug #23-24 fix)
            extracted_urls = preprocess_metadata.get('urls', {}).get('urls', [])
            extracted_media = preprocess_metadata.get('media', {})

            # Extract title from PDF filename or content
            title = self._extract_pdf_title(url, original_content)

            # Chunk the content if it exceeds 40KB
            chunks = self._chunk_markdown_with_context(markdown_content)

            # Process each chunk as a separate document
            total_indexed = 0
            processed_chunks = []

            for i, chunk in enumerate(chunks):
                chunk_content = chunk["content"]

                # Create document object for this chunk
                chunk_id = f"pdf_{hashlib.sha1(url.encode()).hexdigest()[:12]}_chunk_{i}"
                document = {
                    "source_document_name": chunk_id,
                    "document_title": f"{title} (Chunk {i+1}/{len(chunks)})" if len(chunks) > 1 else title,
                    "document_type": "PDF",
                    "document_date": None,
                    "page_source": url,
                    "page_content": chunk_content,
                    "detailed_summary": None,
                    "key_facts": [],
                    "entities": {},
                    "keywords": [],
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "chunk_size_bytes": chunk["size"]
                }

                # Get original content for this chunk (Bug #23-24 fix)
                chunk_original = self._get_original_content_for_chunk(
                    original_content, i, len(chunks)
                )

                # Prepare for hybrid embedding with full metadata
                embedding_doc = {
                    "id": chunk_id,
                    "text": chunk_content,  # Tokenized content for embedding
                    "metadata": {
                        "url": url,
                        "title": title,
                        "document_type": "PDF",
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "chunk_size_bytes": chunk["size"],
                        # Bug #23-24 fix: Include extracted URLs and media for citations
                        "extracted_urls": extracted_urls[:50] if extracted_urls else [],
                        "extracted_media": {
                            "images": [img.get('src', '') for img in extracted_media.get('images', [])[:20]],
                            "alt_texts": [img.get('alt', '') for img in extracted_media.get('images', [])[:20]],
                        },
                        # Bug #24 fix: Store original (non-tokenized) content for retrieval
                        "original_content": chunk_original,
                        "preprocessing_applied": preprocess_metadata.get('preprocessing_applied', []),
                    }
                }

                # Generate embedding and index this chunk
                indexed_count = await self.embedder.index_documents_memory([embedding_doc], namespace)

                total_indexed += indexed_count
                processed_chunks.append(document)

            if total_indexed > 0:
                logger.info(f"Successfully processed and indexed PDF {url} in {len(chunks)} chunks")
                self.stats["documents_indexed"] += total_indexed
                self.stats["pdf_stats"]["pdfs_processed"] += 1

                # Record successful URL result
                self._record_url_result(
                    url=url,
                    status="indexed",
                    content_type="pdf",
                    document_count=total_indexed,
                    content_size_bytes=processed_size_kb * 1024,
                    title=title
                )

                # Return the first chunk as the main document
                return processed_chunks[0] if processed_chunks else None
            else:
                logger.error(f"Failed to index PDF from {url}")
                self.stats["pdf_stats"]["pdfs_failed"] += 1
                # Record failed URL result
                self._record_url_result(
                    url=url,
                    status="failed",
                    content_type="pdf",
                    error_message="Failed to index PDF content"
                )
                return None

        except Exception as e:
            logger.error(f"Error processing PDF URL {url}: {e}", exc_info=True)
            self.stats["pdf_stats"]["pdfs_failed"] += 1
            # Record failed URL result with exception
            self._record_url_result(
                url=url,
                status="failed",
                content_type="pdf",
                error_message=str(e)
            )
            return None

    def _extract_pdf_title(self, url: str, content: str) -> str:
        """Extract title from PDF URL or content."""
        try:
            # Try to extract from URL filename
            from urllib.parse import urlparse, unquote
            parsed = urlparse(url)
            path = unquote(parsed.path)
            if path:
                filename = path.split('/')[-1]
                if filename.lower().endswith('.pdf'):
                    # Remove .pdf extension and clean up
                    title = filename[:-4].replace('_', ' ').replace('-', ' ')
                    title = ' '.join(title.split())  # Normalize whitespace
                    if title and len(title) > 3:
                        return title[:200]

            # Try to extract from content (first heading)
            title = self._extract_title_from_content(content)
            if title != "Untitled":
                return title

            return "PDF Document"
        except Exception:
            return "PDF Document"

    # 40KB threshold in bytes for chunking (Pinecone metadata limit)
    # Using 32KB default to leave 8KB buffer for metadata overhead
    MAX_CHUNK_SIZE_BYTES = int(os.getenv("PINECONE_METADATA_LIMIT_BYTES", "32000"))

    def _chunk_markdown_with_context(self, markdown_content: str, max_chunk_size: int = None) -> List[Dict[str, Any]]:
        """
        Chunk markdown content with parent heading context preservation.
        Only chunks if content exceeds 40KB threshold.
        """
        try:
            content_size_bytes = len(markdown_content.encode('utf-8'))
            
            # If content is under 40KB, return as single chunk
            if content_size_bytes <= self.MAX_CHUNK_SIZE_BYTES:
                logger.info(f"Content size {content_size_bytes/1024:.1f}KB is under 40KB - no chunking needed")
                return [{
                    "content": markdown_content,
                    "heading_context": [],
                    "size": content_size_bytes
                }]
            
            logger.info(f"Content size {content_size_bytes/1024:.1f}KB exceeds 40KB - chunking with context preservation")
            
            # Use 40KB as chunk size if not provided
            if max_chunk_size is None:
                max_chunk_size = self.MAX_CHUNK_SIZE_BYTES
            
            lines = markdown_content.split('\n')
            chunks = []
            current_chunk = []
            current_heading_stack = []
            current_size = 0
            
            for line in lines:
                line_bytes = len(line.encode('utf-8')) + 1  # +1 for newline
                
                # Check if this is a heading
                if line.strip().startswith('#'):
                    # If we have content and adding this heading would exceed limit, save current chunk
                    if current_chunk and current_size + line_bytes > max_chunk_size:
                        # Save current chunk with context
                        chunk_text = '\n'.join(current_chunk)
                        if chunk_text.strip():
                            chunks.append({
                                "content": chunk_text,
                                "heading_context": current_heading_stack.copy(),
                                "size": current_size
                            })
                        
                        # Start new chunk
                        current_chunk = []
                        current_size = 0
                    
                    # Update heading stack
                    heading_level = len(line) - len(line.lstrip('#'))
                    heading_text = line.strip('#').strip()
                    
                    # Trim stack to current level
                    current_heading_stack = [h for h in current_heading_stack if h['level'] < heading_level]
                    current_heading_stack.append({
                        "level": heading_level,
                        "text": heading_text
                    })
                
                # Add line to current chunk
                current_chunk.append(line)
                current_size += line_bytes
                
                # If chunk is getting too large, split it
                if current_size > max_chunk_size and current_chunk:
                    # Find a good split point (preferably at paragraph boundary)
                    split_point = len(current_chunk)
                    for i in range(len(current_chunk) - 1, 0, -1):
                        if current_chunk[i].strip() == '' and i > len(current_chunk) // 2:
                            split_point = i + 1
                            break
                    
                    # Create chunk from current content up to split point
                    chunk_content = '\n'.join(current_chunk[:split_point])
                    if chunk_content.strip():
                        # Add heading context to the beginning of the chunk for context
                        context_header = self._build_context_header(current_heading_stack)
                        full_chunk = context_header + chunk_content if context_header else chunk_content
                        
                        chunks.append({
                            "content": full_chunk,
                            "heading_context": current_heading_stack.copy(),
                            "size": len(full_chunk.encode('utf-8'))
                        })
                    
                    # Continue with remaining content
                    current_chunk = current_chunk[split_point:]
                    current_size = sum(len(line.encode('utf-8')) + 1 for line in current_chunk)
            
            # Add final chunk
            if current_chunk:
                chunk_content = '\n'.join(current_chunk)
                if chunk_content.strip():
                    context_header = self._build_context_header(current_heading_stack)
                    full_chunk = context_header + chunk_content if context_header else chunk_content
                    
                    chunks.append({
                        "content": full_chunk,
                        "heading_context": current_heading_stack.copy(),
                        "size": len(full_chunk.encode('utf-8'))
                    })
            
            logger.info(f"Created {len(chunks)} chunks from {content_size_bytes/1024:.1f}KB markdown content")
            return chunks
            
        except Exception as e:
            logger.error(f"Error chunking markdown content: {e}")
            # Fallback: return single chunk
            return [{
                "content": markdown_content,
                "heading_context": [],
                "size": len(markdown_content.encode('utf-8'))
            }]

    def _filter_media(self, media_items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Filter out irrelevant media (SVGs, small icons, data URIs) to save metadata space.
        """
        filtered = []
        for item in media_items:
            src = item.get('src', '').lower()
            if not src:
                continue
                
            # Filter out data URIs (often small icons or huge blobs)
            if src.startswith('data:'):
                continue
                
            # Filter out SVGs and ICOs
            if src.endswith('.svg') or src.endswith('.ico'):
                continue
                
            # Filter common icon keywords in URL users often want to skip
            if any(x in src for x in ['/icon/', 'favicon', 'logo.png', 'logo.jpg']):
               # Optional: keep logos if main image, but usually they are noise in search list
               pass
            
            filtered.append(item)
            
        return filtered[:10]  # Keep top 10 relevant images max

    def _build_context_header(self, heading_stack: List[Dict[str, Any]]) -> str:
        """Build a context header string from the heading stack."""
        if not heading_stack:
            return ""
        
        context_lines = []
        for heading in heading_stack:
            level = heading["level"]
            text = heading["text"]
            context_lines.append(f"{'#' * level} {text}")
        
        return '\n'.join(context_lines) + '\n\n---\n\n'

    def _add_heading_context_to_chunk(self, chunk: Dict[str, Any]) -> str:
        """Add parent heading context to chunk content."""
        try:
            if not chunk["heading_context"]:
                return chunk["content"]

            # Build context string
            context_lines = []
            for heading in chunk["heading_context"]:
                level = heading["level"]
                text = heading["text"]
                context_lines.append(f"{'#' * level} {text}")

            # Combine context with content
            if context_lines:
                context = '\n'.join(context_lines) + '\n\n'
                return context + chunk["content"]
            else:
                return chunk["content"]

        except Exception as e:
            logger.error(f"Error adding heading context: {e}")
            return chunk["content"]

    def _get_original_content_for_chunk(
        self,
        original_content: str,
        chunk_index: int,
        total_chunks: int,
        max_bytes: int = 30000  # 30KB limit for original_content (leave room for other metadata)
    ) -> str:
        """
        Bug #23-24 fix: Get the corresponding portion of original content for a chunk.
        This enables storing original (non-tokenized) content for citation purposes.
        
        CRITICAL: Uses BYTE-based truncation, not character-based, for UTF-8 safety.

        Args:
            original_content: Full original content before tokenization
            chunk_index: Index of current chunk (0-based)
            total_chunks: Total number of chunks
            max_bytes: Maximum size in BYTES to return (not characters!)

        Returns:
            Portion of original content corresponding to this chunk
        """
        def truncate_to_bytes(text: str, max_bytes: int) -> str:
            """Safely truncate text to fit within byte limit."""
            if not text or max_bytes <= 0:
                return ""
            encoded = text.encode('utf-8')
            if len(encoded) <= max_bytes:
                return text
            truncated = encoded[:max_bytes]
            while truncated:
                try:
                    return truncated.decode('utf-8')
                except UnicodeDecodeError:
                    truncated = truncated[:-1]
            return ""

        try:
            if total_chunks == 1:
                # Single chunk - return entire original (truncated if needed)
                return truncate_to_bytes(original_content, max_bytes)

            # Calculate approximate portion size in characters first
            content_length = len(original_content)
            portion_size = content_length // total_chunks

            # Calculate start and end positions with overlap
            overlap = min(500, portion_size // 4)  # 500 chars overlap or 25% of portion
            start = max(0, (chunk_index * portion_size) - overlap)
            end = min(content_length, ((chunk_index + 1) * portion_size) + overlap)

            # Extract portion
            chunk_original = original_content[start:end]

            # Truncate by BYTES (not characters) to ensure we fit
            return truncate_to_bytes(chunk_original, max_bytes)

        except Exception as e:
            logger.error(f"Error getting original content for chunk: {e}")
            # Fallback: return beginning of original content (byte-safe)
            return truncate_to_bytes(original_content, max_bytes)

    async def _check_content_type_head(self, url: str, timeout: int = 10) -> Optional[str]:
        """
        Perform a HEAD request to check Content-Type before full download.
        This helps detect PDFs from dynamic URLs that don't have .pdf extension.

        Args:
            url: URL to check
            timeout: Request timeout in seconds

        Returns:
            Content-Type header value or None if request fails
        """
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '')
                        logger.debug(f"HEAD check for {url}: Content-Type={content_type}")
                        return content_type
                    # Some servers don't support HEAD, return None to proceed with GET
                    return None
        except Exception as e:
            logger.debug(f"HEAD request failed for {url}: {e}")
            return None

    def _detect_pdf_from_content(self, content: bytes) -> bool:
        """
        Detect if content is a PDF by checking magic bytes.
        PDF files start with '%PDF-' (hex: 25 50 44 46 2D).

        Args:
            content: First bytes of content

        Returns:
            True if content appears to be a PDF
        """
        if content and len(content) >= 5:
            return content[:5] == b'%PDF-'
        return False

    async def _process_single_url_with_crawl4ai(self, url: str, namespace: Optional[str] = None, pre_fetched_result: Any = None) -> Optional[Dict[str, Any]]:
        """Process a single URL using Crawl4AI: fetch → extract → chunk → embed → index."""
        try:
            logger.info(f"Processing URL: {url}")

            # Layer 1: Check URL patterns first (fast, no network)
            if self._is_pdf_url(url):
                logger.info(f"Detected PDF URL by pattern: {url}")
                return await self._process_pdf_url(url, namespace)

            # Layer 2: Check pre-fetched result for Content-Type (if available from Crawl4AI)
            if pre_fetched_result:
                # Check response headers if available
                response_headers = getattr(pre_fetched_result, 'response_headers', {}) or {}
                content_type = response_headers.get('Content-Type', '') or response_headers.get('content-type', '')
                if content_type and 'application/pdf' in content_type.lower():
                    logger.info(f"Detected PDF from response headers: {url}")
                    return await self._process_pdf_url(url, namespace)

            # Layer 3: For URLs without clear indicators, do a quick HEAD check
            # This catches dynamic URLs like /api/document/123 that return PDFs
            if not pre_fetched_result and not url.lower().endswith(('.html', '.htm', '.php', '.asp', '.aspx', '.jsp')):
                head_content_type = await self._check_content_type_head(url)
                if head_content_type and 'application/pdf' in head_content_type.lower():
                    logger.info(f"Detected PDF from HEAD request: {url}")
                    return await self._process_pdf_url(url, namespace)

            markdown_content = None
            html_content = None  # Store HTML for title extraction

            # Use pre-fetched result if available (from Deep Crawl)
            if pre_fetched_result:
                if hasattr(pre_fetched_result, 'markdown') and pre_fetched_result.markdown:
                    markdown_content = pre_fetched_result.markdown.strip()
                if hasattr(pre_fetched_result, 'html') and pre_fetched_result.html:
                    html_content = pre_fetched_result.html
                    
                    # Bug #28 fix: Fallback to markdownify when crawl4ai markdown extraction fails
                    # This is a workaround for crawl4ai's LXMLWebScrapingStrategy bug on complex pages
                    if (not markdown_content or len(markdown_content) < 100) and len(html_content) > 500:
                        logger.warning(f"Extracted markdown too short ({len(markdown_content) if markdown_content else 0} chars). Using markdownify fallback.")
                        try:
                            from markdownify import markdownify as md
                            from bs4 import BeautifulSoup
                            
                            # Parse HTML and extract main content (skip scripts/styles)
                            soup = BeautifulSoup(html_content, 'lxml')
                            
                            # Remove script and style elements
                            for script_or_style in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                                script_or_style.decompose()
                            
                            # Try to find main content areas
                            main_content = soup.find(['main', 'article']) or soup.find('div', {'id': 'content'}) or soup.find('div', {'id': 'mw-content-text'}) or soup.body
                            
                            if main_content:
                                fallback_md = md(str(main_content), heading_style="ATX", strip=['a'])
                                if fallback_md and len(fallback_md) > len(markdown_content or ""):
                                    markdown_content = fallback_md.strip()
                                    logger.info(f"Markdownify fallback successful: {len(markdown_content)} chars extracted")
                        except Exception as e:
                            logger.error(f"Markdownify fallback failed: {e}")
            else:
                # Fetch fresh if not pre-fetched
                # Bug #25 fix: Use WebScrapingStrategy (Pruning) for robust content extraction
                run_config = CrawlerRunConfig(
                    scraping_strategy=WebScrapingStrategy(),
                    verbose=True,
                    magic=True
                )
                
                async with AsyncWebCrawler(
                    verbose=True,
                    headless=True,
                    browser_type="chromium"
                ) as crawler:
                    # Production Enhancement: Per-URL timeout to prevent indefinite hangs
                    try:
                        result = await asyncio.wait_for(
                            crawler.arun(url=url, config=run_config),
                            timeout=60  # 60 seconds max per URL
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"Fresh fetch timed out after 60s for {url}")
                        self._record_url_result(
                            url=url,
                            status="failed",
                            content_type="html",
                            error_message="Fetch timed out after 60 seconds"
                        )
                        return None

                    # Capture HTML for title extraction
                    if hasattr(result, 'html') and result.html:
                        html_content = result.html
                    elif hasattr(result, 'content') and result.content:
                        html_content = result.content

                    # Prefer markdown when available; otherwise derive from HTML, or fallback if short
                    if hasattr(result, 'markdown') and result.markdown:
                        markdown_content = result.markdown.strip()
                    
                    # Production Fix #1: Apply markdownify fallback to fresh fetches too
                    # This ensures consistent behavior between pre-fetched and fresh content
                    if (not markdown_content or len(markdown_content) < 100) and html_content and len(html_content) > 500:
                        logger.warning(f"Fresh fetch: markdown too short ({len(markdown_content) if markdown_content else 0} chars). Using markdownify fallback.")
                        try:
                            from markdownify import markdownify as md
                            from bs4 import BeautifulSoup
                            
                            # Parse HTML and extract main content (skip scripts/styles)
                            soup = BeautifulSoup(html_content, 'lxml')
                            
                            # Remove script and style elements
                            for script_or_style in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                                script_or_style.decompose()
                            
                            # Try to find main content areas
                            main_content = soup.find(['main', 'article']) or soup.find('div', {'id': 'content'}) or soup.find('div', {'id': 'mw-content-text'}) or soup.body
                            
                            if main_content:
                                fallback_md = md(str(main_content), heading_style="ATX", strip=['a'])
                                if fallback_md and len(fallback_md) > len(markdown_content or ""):
                                    markdown_content = fallback_md.strip()
                                    logger.info(f"Fresh fetch markdownify fallback successful: {len(markdown_content)} chars extracted")
                        except Exception as e:
                            logger.error(f"Fresh fetch markdownify fallback failed: {e}")

            if not markdown_content:
                logger.warning(f"No content extracted from {url}")
                # Record skipped URL result
                self._record_url_result(
                    url=url,
                    status="skipped",
                    content_type="html",
                    error_message="No content extracted"
                )
                return None

            # Clean and validate markdown content
            if len(markdown_content) < 100:  # Basic content validation
                logger.warning(f"Content too short from {url}: {len(markdown_content)} chars")
                logger.warning(f"Short content preview: {markdown_content[:200]!r}")
                
                # Check for common blocking/redirect messages
                lower_content = markdown_content.lower()
                if "access denied" in lower_content or "forbidden" in lower_content:
                     logger.warning("Likely blocked by WAF/Bot Protection")
                elif "redirect" in lower_content or "moved" in lower_content:
                     logger.warning("Likely a redirect page")

                # Record skipped URL result
                self._record_url_result(
                    url=url,
                    status="skipped",
                    content_type="html",
                    error_message=f"Content too short ({len(markdown_content)} chars). Content: {markdown_content[:100]!r}"
                )
                return None

            # Log original content size
            original_size_kb = len(markdown_content.encode('utf-8')) / 1024
            logger.info(f"Raw content from {url}: {original_size_kb:.1f}KB")

            # Bug #23-24 fix: Store original content BEFORE preprocessing for citations
            original_content = markdown_content

            # Apply content preprocessing (media tokenization, URL tokenization, etc.)
            # This runs BEFORE embedding to prevent embedding pollution
            # The tokenized content is used for embeddings, original is stored for retrieval
            markdown_content, preprocess_metadata = self.preprocessor.process(
                markdown_content, content_type="markdown"
            )

            # Update preprocessing stats
            self.stats["preprocessing_stats"]["urls_preprocessed"] += 1
            if "processed_length" in preprocess_metadata:
                reduction = preprocess_metadata.get("original_length", 0) - preprocess_metadata.get("processed_length", 0)
                self.stats["preprocessing_stats"]["total_reduction_bytes"] += reduction

            processed_size_kb = len(markdown_content.encode('utf-8')) / 1024
            logger.info(f"Preprocessed content from {url}: {processed_size_kb:.1f}KB "
                       f"(reduced {preprocess_metadata.get('reduction_percent', 0)}%)")

            # Bug #23-24 fix: Extract URLs and media from preprocessing metadata
            extracted_urls = preprocess_metadata.get('urls', {}).get('urls', [])
            extracted_media = preprocess_metadata.get('media', {})

            # Extract title from ORIGINAL content before tokenization
            # Pass HTML content for better title extraction (contains <title> tag)
            title = self._extract_title_from_content(original_content, html_content)

            # Chunk the content if it exceeds 40KB (uses 40KB threshold internally)
            chunks = self._chunk_markdown_with_context(markdown_content)
            
            # Process each chunk as a separate document
            total_indexed = 0
            processed_chunks = []
            
            for i, chunk in enumerate(chunks):
                # Content already has context header embedded from chunking
                chunk_content = chunk["content"]
                
                # Create document object for this chunk
                chunk_id = f"html_{hashlib.sha1(url.encode()).hexdigest()[:12]}_chunk_{i}"
                document = {
                    "source_document_name": chunk_id,
                    "document_title": f"{title} (Chunk {i+1}/{len(chunks)})" if len(chunks) > 1 else title,
                    "document_type": "HTML",
                    "document_date": None,
                    "page_source": url,
                    "page_content": chunk_content,
                    "detailed_summary": None,
                    "key_facts": [],
                    "entities": {},
                    "keywords": [],
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "chunk_size_bytes": chunk["size"]
                }
                
                # Bug #23-24 fix: Prepare original content for this chunk
                # Calculate which portion of original content corresponds to this chunk
                chunk_original = self._get_original_content_for_chunk(
                    original_content, i, len(chunks)
                )

                # Prepare for hybrid embedding with preserved metadata
                embedding_doc = {
                    "id": chunk_id,
                    "text": chunk_content,  # Tokenized content for embedding generation
                    "metadata": {
                        "url": url,
                        "title": title,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "original_title": title,
                        "chunk_size_bytes": chunk["size"],
                        # Bug #27 fix: Metadata Optimization for Pinecone (40KB limit)
                        # 1. REMOVE extracted_urls entirely (user request)
                        
                        # 2. Filter and limit media (no SVGs/icons)
                        "extracted_media": {
                            "images": [img.get('src', '') for img in self._filter_media(extracted_media.get('images', []))],
                            "alt_texts": [img.get('alt', '') for img in self._filter_media(extracted_media.get('images', []))],
                        },
                        
                        # 3. original_content is already byte-truncated by _get_original_content_for_chunk
                        # Do NOT apply additional character truncation here as it can exceed byte limits
                        "original_content": chunk_original if chunk_original else "",
                        "preprocessing_applied": preprocess_metadata.get('preprocessing_applied', []),
                    }
                }
                
                # Generate embedding and index this chunk
                # print(f"🔍 DEBUG: About to index chunk {i+1}/{len(chunks)} for URL: {url}")
                
                indexed_count = await self.embedder.index_documents_memory([embedding_doc], namespace)
                
                total_indexed += indexed_count
                processed_chunks.append(document)
            
            if total_indexed > 0:
                logger.info(f"Successfully processed and indexed {url} in {len(chunks)} chunks")
                self.stats["documents_indexed"] += total_indexed

                # Record successful URL result
                self._record_url_result(
                    url=url,
                    status="indexed",
                    content_type="html",
                    document_count=total_indexed,
                    content_size_bytes=int(processed_size_kb * 1024),
                    title=title
                )

                # Return the first chunk as the main document (for compatibility)
                main_document = processed_chunks[0] if processed_chunks else None
                return main_document
            else:
                logger.error(f"Failed to index document from {url}")
                # Record failed URL result
                self._record_url_result(
                    url=url,
                    status="failed",
                    content_type="html",
                    error_message="Failed to index document"
                )
                return None

        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            # Record failed URL result with exception
            self._record_url_result(
                url=url,
                status="failed",
                content_type="html",
                error_message=str(e)
            )
            return None

    def _html_to_markdown(self, html: str) -> Optional[str]:
        """Convert raw HTML string to markdown using MarkItDown with a temp file fallback."""
        try:
            import tempfile
            from markitdown import MarkItDown
            md = MarkItDown()
            # Write to a temp file because MarkItDown works on file paths more reliably
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as tmp:
                tmp.write(html)
                temp_html_path = tmp.name
            try:
                result = md.convert(temp_html_path)
                return (result.text_content or '').strip()
            finally:
                import os
                try:
                    os.unlink(temp_html_path)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed HTML→Markdown conversion: {e}")
            return None


    async def process_crawl_results(self, crawl_results: List[Any], namespace: Optional[str] = None) -> Dict[str, Any]:
        """
        Process pre-fetched results from Crawl4AI Deep Crawl.
        Returns processing results and statistics.
        Sends progress webhooks periodically during processing.
        """
        try:
            logger.info(f"🚀 Starting processing of {len(crawl_results)} Deep Crawl results")
            
            # Deduplicate crawl results by URL to prevent processing the same page twice
            # Crawl4AI's BFSDeepCrawlStrategy may return the same URL multiple times
            seen_urls = set()
            deduplicated_results = []
            for result in crawl_results:
                url = getattr(result, 'url', None)
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    deduplicated_results.append(result)
                elif url:
                    logger.debug(f"Skipping duplicate URL: {url}")
            
            if len(deduplicated_results) < len(crawl_results):
                logger.info(f"   Deduplicated: {len(crawl_results)} → {len(deduplicated_results)} unique URLs")
            
            crawl_results = deduplicated_results

            # Ensure embedder is initialized (crucial for GeminiDocumentEmbedder)
            if hasattr(self.embedder, "initialize"):
                logger.info("Ensuring embedder is initialized...")
                success = await self.embedder.initialize()
                if not success:
                    logger.error("Failed to initialize embedder")
                    return {
                        "status": "failed",
                        "error": "Failed to initialize embedding model",
                        "stats": self.stats,
                        "url_results": []
                    }

            import time
            self.stats["start_time"] = time.time()
            total_urls = len(crawl_results)

            # Process results in parallel with controlled concurrency and progress updates
            processed_documents = await self._process_results_parallel_with_progress(
                crawl_results,
                namespace,
                total_urls
            )

            # Update stats
            self.stats["urls_processed"] = len(crawl_results)
            self.stats["urls_successful"] = len([d for d in processed_documents if d is not None])
            self.stats["urls_failed"] = len([d for d in processed_documents if d is None])

            # Calculate final stats
            self.stats["duration"] = time.time() - self.stats["start_time"]

            logger.info(f"Processing completed:")
            logger.info(f"  - URLs processed: {self.stats['urls_processed']}")
            logger.info(f"  - URLs successful: {self.stats['urls_successful']}")
            logger.info(f"  - Documents indexed: {self.stats['documents_indexed']}")
            logger.info(f"  - Duration: {self.stats['duration']:.2f} seconds")

            # Update database with final stats
            if self.db_manager and self.task_id:
                await self.db_manager.update_task_status(
                    self.task_id,
                    "processing_urls",
                    urls_processed=self.stats['urls_processed'],
                    documents_indexed=self.stats['documents_indexed']
                )

            # Send final progress webhook
            if self.progress_callback:
                try:
                    await self.progress_callback(
                        "processing_urls",
                        total_urls,
                        self.stats['urls_processed'],
                        self.stats['documents_indexed']
                    )
                except Exception as e:
                    logger.debug(f"Final progress callback failed (non-critical): {e}")

            return {
                "status": "completed",
                "processed_documents": processed_documents,
                "stats": self.stats,
                "message": f"Successfully processed {self.stats['urls_successful']}/{self.stats['urls_processed']} URLs",
                # Bug #26 fix: Include per-URL results for visibility
                "url_results": self.url_results
            }

        except Exception as e:
            logger.error(f"Error in processing: {e}")
            self.stats["errors"] += 1
            return {
                "status": "failed",
                "error": str(e),
                "processed_documents": [],
                "stats": self.stats,
                # Include any results collected before failure
                "url_results": self.url_results
            }

    async def _process_results_parallel(self, results: List[Any], namespace: Optional[str] = None, max_concurrency: int = 5) -> List[Optional[Dict[str, Any]]]:
        """Process multiple CrawlResults in parallel with controlled concurrency."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def process_with_semaphore(result: Any):
            async with semaphore:
                try:
                    return await self._process_single_url_with_crawl4ai(result.url, namespace, pre_fetched_result=result)
                except Exception as e:
                    logger.error(f"❌ Error processing result for {result.url}: {e}")
                    return None

        # Process all results in parallel
        tasks = [process_with_semaphore(r) for r in results]
        processed_docs = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter exceptions
        final_docs = []
        for doc in processed_docs:
            if isinstance(doc, Exception):
                self.stats["errors"] += 1
                final_docs.append(None)
            else:
                final_docs.append(doc)

        return final_docs

    async def _process_results_parallel_with_progress(
        self,
        results: List[Any],
        namespace: Optional[str] = None,
        total_urls: int = 0,
        max_concurrency: int = 5,
        progress_interval: int = 5
    ) -> List[Optional[Dict[str, Any]]]:
        """
        Process multiple CrawlResults in parallel with progress updates.
        Sends progress webhook every `progress_interval` completed URLs.
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        processed_count = 0
        last_progress_sent = 0

        async def process_with_semaphore_and_progress(result: Any, index: int):
            nonlocal processed_count, last_progress_sent
            async with semaphore:
                try:
                    doc = await self._process_single_url_with_crawl4ai(result.url, namespace, pre_fetched_result=result)
                    processed_count += 1

                    # Send progress update every N URLs
                    if self.progress_callback and (processed_count - last_progress_sent) >= progress_interval:
                        last_progress_sent = processed_count
                        try:
                            await self.progress_callback(
                                "processing_urls",
                                total_urls,
                                processed_count,
                                self.stats['documents_indexed']
                            )
                        except Exception as e:
                            logger.debug(f"Progress callback failed (non-critical): {e}")

                    return doc
                except Exception as e:
                    logger.error(f"❌ Error processing result for {result.url}: {e}")
                    processed_count += 1
                    return None

        # Process all results in parallel
        tasks = [process_with_semaphore_and_progress(r, i) for i, r in enumerate(results)]
        processed_docs = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter exceptions
        final_docs = []
        for doc in processed_docs:
            if isinstance(doc, Exception):
                self.stats["errors"] += 1
                final_docs.append(None)
            else:
                final_docs.append(doc)

        return final_docs

    # Keep old method for backward compatibility if needed, but it's largely superseded
    async def process_urls_iteratively(self, urls: List[str], namespace: Optional[str] = None) -> Dict[str, Any]:
        """Legacy method: Process URLs by fetching them fresh."""
        # Just fetch them one by one using the same logic
        return await self.process_crawl_results([type('MockResult', (), {'url': u, 'markdown': None, 'html': None})() for u in urls], namespace)

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics including PDF download stats."""
        stats = self.stats.copy()

        # Include PDF downloader stats if available
        if self.pdf_downloader:
            stats["pdf_download_stats"] = self.pdf_downloader.get_stats()

        return stats

    def _check_memory_usage(self) -> bool:
        """Check if memory usage is within acceptable limits."""
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024

            if memory_mb > self.max_memory_mb:
                logger.warning(f"High memory usage: {memory_mb:.1f}MB (limit: {self.max_memory_mb}MB)")
                return False
            return True
        except Exception:
            return True

    async def cleanup(self):
        """
        Cleanup resources - should be called when processing is complete.
        Closes the PDF downloader session and releases connections.
        """
        if self.pdf_downloader:
            try:
                await self.pdf_downloader.close()
                logger.info("PDF downloader session closed")
            except Exception as e:
                logger.warning(f"Error closing PDF downloader: {e}")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup resources."""
        await self.cleanup()
