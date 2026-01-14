"""
Memory-only streaming indexer for production environments.
Processes content entirely in memory without creating temporary files.
"""

import asyncio
import logging
import hashlib
import io
from typing import Optional, Dict, Any, List
from pathlib import Path
import re

from .crawler import WebCrawler
from .embedder import DocumentEmbedder
from .config import PipelineConfig

logger = logging.getLogger(__name__)


class MemoryStreamingIndexer:
    """
    Memory-only streaming indexer that processes content entirely in memory.
    Perfect for production environments with no temporary file creation.
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.embedder = DocumentEmbedder(config.embedding)
        
        # In-memory document buffer
        self.document_buffer: List[Dict[str, Any]] = []
        self.buffer_size = 10  # Process in batches of 10
        
        # Statistics
        self.stats = {
            "pages_processed": 0,
            "documents_indexed": 0,
            "errors": 0,
            "start_time": None
        }
        
        logger.info("MemoryStreamingIndexer initialized (memory-only mode)")

    def _extract_title_from_html(self, html_content: str) -> str:
        """Extract title from HTML content."""
        try:
            # Simple regex to extract title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
                # Clean up the title
                title = re.sub(r'\s+', ' ', title)
                return title[:200]  # Limit title length
            return "Untitled"
        except Exception:
            return "Untitled"

    def _clean_html_content(self, html_content: str) -> str:
        """Clean HTML content for better processing."""
        try:
            # Remove script and style elements
            html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.IGNORECASE | re.DOTALL)
            html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove comments
            html_content = re.sub(r'<!--.*?-->', '', html_content, flags=re.DOTALL)
            
            # Remove extra whitespace
            html_content = re.sub(r'\s+', ' ', html_content)
            
            return html_content.strip()
        except Exception as e:
            logger.warning(f"Error cleaning HTML content: {e}")
            return html_content

    def _html_to_markdown_memory(self, html_content: str) -> str:
        """
        Convert HTML to Markdown entirely in memory.
        Simple but effective conversion for most content.
        """
        try:
            # Clean HTML first
            html_content = self._clean_html_content(html_content)
            
            # Simple HTML to Markdown conversion
            markdown = html_content
            
            # Convert headers
            markdown = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<h4[^>]*>(.*?)</h4>', r'#### \1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<h5[^>]*>(.*?)</h5>', r'##### \1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<h6[^>]*>(.*?)</h6>', r'###### \1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            
            # Convert paragraphs
            markdown = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            
            # Convert links
            markdown = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'[\2](\1)', markdown, flags=re.IGNORECASE | re.DOTALL)
            
            # Convert bold and italic
            markdown = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', markdown, flags=re.IGNORECASE | re.DOTALL)
            
            # Convert lists
            markdown = re.sub(r'<ul[^>]*>(.*?)</ul>', r'\1', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<ol[^>]*>(.*?)</ol>', r'\1', markdown, flags=re.IGNORECASE | re.DOTALL)
            markdown = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', markdown, flags=re.IGNORECASE | re.DOTALL)
            
            # Convert line breaks
            markdown = re.sub(r'<br[^>]*/?>', r'\n', markdown, flags=re.IGNORECASE)
            
            # Remove remaining HTML tags
            markdown = re.sub(r'<[^>]+>', '', markdown)
            
            # Clean up whitespace
            markdown = re.sub(r'\n\s*\n\s*\n', '\n\n', markdown)  # Multiple newlines to double
            markdown = re.sub(r'[ \t]+', ' ', markdown)  # Multiple spaces to single
            markdown = markdown.strip()
            
            return markdown
            
        except Exception as e:
            logger.error(f"Error converting HTML to Markdown: {e}")
            # Fallback: just strip HTML tags
            return re.sub(r'<[^>]+>', '', html_content)

    async def process_html_page(self, url: str, html_content: str):
        """Process an HTML page entirely in memory."""
        try:
            logger.info(f"Processing HTML page in memory: {url}")
            
            # Convert HTML to Markdown in memory
            markdown_content = self._html_to_markdown_memory(html_content)
            
            if not markdown_content.strip():
                logger.warning(f"Empty content extracted from {url}")
                return
            
            # Create document object
            document = {
                "source_document_name": f"html_{hashlib.sha1(url.encode()).hexdigest()[:12]}",
                "document_title": self._extract_title_from_html(html_content),
                "document_type": "HTML",
                "document_date": None,
                "page_source": url,
                "page_content": markdown_content,
                "detailed_summary": None,
                "key_facts": [],
                "entities": {},
                "keywords": []
            }
            
            # Add to buffer
            self.document_buffer.append(document)
            self.stats["pages_processed"] += 1
            
            # Process buffer if full
            if len(self.document_buffer) >= self.buffer_size:
                await self._process_buffer()
            
            logger.info(f"Successfully processed HTML page in memory: {url}")
            
        except Exception as e:
            logger.error(f"Error processing HTML page {url}: {e}")
            self.stats["errors"] += 1

    async def process_downloaded_file(self, url: str, file_content: bytes, file_type: str):
        """Process a downloaded file entirely in memory."""
        try:
            logger.info(f"Processing downloaded file in memory: {url}")
            
            # For now, we'll skip complex file processing in memory-only mode
            # This can be extended later for PDFs, etc. if needed
            logger.info(f"Skipping file processing for {url} (memory-only mode)")
            
        except Exception as e:
            logger.error(f"Error processing downloaded file {url}: {e}")
            self.stats["errors"] += 1

    async def _process_buffer(self):
        """Process the document buffer and index to vector database."""
        if not self.document_buffer:
            return
        
        try:
            logger.info(f"Processing buffer of {len(self.document_buffer)} documents")
            
            # Prepare documents for embedding
            documents = []
            for doc in self.document_buffer:
                # Create embedding-ready document
                embedding_doc = {
                    "id": doc["source_document_name"],
                    "text": doc["page_content"],
                    "metadata": {
                        "title": doc["document_title"],
                        "url": doc["page_source"],
                        "type": doc["document_type"],
                        "source": "memory_streaming"
                    }
                }
                documents.append(embedding_doc)
            
            # Generate embeddings and index
            if documents:
                success_count = await self.embedder.index_documents_memory(documents)
                self.stats["documents_indexed"] += success_count
                logger.info(f"Successfully indexed {success_count} documents to vector database")
            
            # Clear buffer
            self.document_buffer.clear()
            
        except Exception as e:
            logger.error(f"Error processing document buffer: {e}")
            self.stats["errors"] += 1

    async def run_streaming_indexing(self, config: PipelineConfig) -> Dict[str, Any]:
        """Run the complete streaming indexing pipeline."""
        import time
        self.stats["start_time"] = time.time()
        
        try:
            logger.info("Starting memory-only streaming indexing pipeline")
            
            # Initialize crawler
            crawler = WebCrawler(config.crawler)
            
            # Set up callbacks for streaming processing
            crawler.on_page_callback = self.process_html_page
            crawler.on_file_callback = self.process_downloaded_file
            
            # Run crawler
            await crawler.run()
            
            # Process any remaining documents in buffer
            if self.document_buffer:
                await self._process_buffer()
            
            # Calculate final stats
            duration = time.time() - self.stats["start_time"]
            self.stats["duration"] = duration
            
            logger.info(f"Memory-only streaming indexing completed in {duration:.2f} seconds")
            logger.info(f"Stats: {self.stats}")
            
            return {
                "status": "completed",
                "stats": self.stats,
                "message": f"Successfully processed {self.stats['pages_processed']} pages and indexed {self.stats['documents_indexed']} documents"
            }
            
        except Exception as e:
            logger.error(f"Error in streaming indexing pipeline: {e}")
            self.stats["errors"] += 1
            return {
                "status": "failed",
                "error": str(e),
                "stats": self.stats
            }
        finally:
            # Clean up crawler
            if 'crawler' in locals():
                await crawler.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get current processing statistics."""
        return self.stats.copy()

    def cleanup(self):
        """Clean up any resources (memory-only, so minimal cleanup needed)."""
        self.document_buffer.clear()
        logger.info("MemoryStreamingIndexer cleanup completed")
