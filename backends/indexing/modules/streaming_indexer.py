"""
Streaming indexer module for real-time processing and indexing.
Combines crawling, processing, and indexing in a single streaming pipeline.
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable
from pathlib import Path
import tempfile
import os

from .crawler import WebCrawler
from .html_processor import HTMLProcessor
from .pdf_processor import PDFProcessor
from .embedder import DocumentEmbedder
from .config import PipelineConfig

logger = logging.getLogger(__name__)


class StreamingIndexer:
    """Real-time streaming indexer that processes and indexes content as it's crawled."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.html_processor = HTMLProcessor(config.processing)
        self.pdf_processor = PDFProcessor(config.processing)
        self.embedder = DocumentEmbedder(config.embedding)
        
        # Temporary directories for processing
        self.temp_dir = Path(tempfile.mkdtemp())
        self.temp_html_dir = self.temp_dir / "html"
        self.temp_pdf_dir = self.temp_dir / "pdf"
        self.temp_image_dir = self.temp_dir / "images"
        
        # Create temp directories
        self.temp_html_dir.mkdir(exist_ok=True)
        self.temp_pdf_dir.mkdir(exist_ok=True)
        self.temp_image_dir.mkdir(exist_ok=True)
        
        # Document buffer for batch processing
        self.document_buffer = []
        self.buffer_size = 10  # Process in batches of 10
        
        logger.info("StreamingIndexer initialized")

    async def process_html_page(self, url: str, html_content: str):
        """Process an HTML page in real-time."""
        try:
            logger.info(f"Processing HTML page: {url}")
            
            # Convert HTML to Markdown
            temp_html_file = self.temp_html_dir / f"temp_{hash(url)}.html"
            temp_md_file = self.temp_html_dir / f"temp_{hash(url)}.md"
            
            # Write HTML to temp file
            with open(temp_html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Convert to Markdown
            success = self.html_processor.convert_html_to_markdown(html_content, str(temp_md_file))
            
            if success:
                # Read the markdown content
                with open(temp_md_file, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                
                # Create document object
                document = {
                    "source_document_name": f"html_{hash(url)}",
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
                
                # Process buffer if full
                if len(self.document_buffer) >= self.buffer_size:
                    await self._process_buffer()
                
                logger.info(f"Successfully processed HTML page: {url}")
            else:
                logger.error(f"Failed to convert HTML to Markdown: {url}")
            
            # Clean up temp files
            if temp_html_file.exists():
                temp_html_file.unlink()
            if temp_md_file.exists():
                temp_md_file.unlink()
                
        except Exception as e:
            logger.error(f"Error processing HTML page {url}: {e}")

    async def process_downloaded_file(self, url: str, file_path: str):
        """Process a downloaded file in real-time."""
        try:
            logger.info(f"Processing downloaded file: {url}")
            
            file_path_obj = Path(file_path)
            file_ext = file_path_obj.suffix.lower()
            
            # Process based on file type
            if file_ext == '.pdf':
                result = self.pdf_processor.process_pdf(
                    file_path_obj, 
                    self.temp_pdf_dir, 
                    self.temp_image_dir
                )
            elif file_ext in ['.docx', '.doc']:
                result = self.pdf_processor.process_word_document(
                    file_path_obj, 
                    self.temp_pdf_dir
                )
            elif file_ext in ['.xlsx', '.xls']:
                result = self.pdf_processor.process_excel_file(
                    file_path_obj, 
                    self.temp_pdf_dir
                )
            elif file_ext == '.csv':
                result = self.pdf_processor.process_csv_file(
                    file_path_obj, 
                    self.temp_pdf_dir
                )
            else:
                logger.warning(f"Unsupported file type: {file_ext}")
                return
            
            if result:
                # Read the processed content
                with open(result, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Create document object
                document = {
                    "source_document_name": f"file_{hash(url)}",
                    "document_title": file_path_obj.stem,
                    "document_type": file_ext.upper().lstrip('.'),
                    "document_date": None,
                    "page_source": url,
                    "page_content": content,
                    "detailed_summary": None,
                    "key_facts": [],
                    "entities": {},
                    "keywords": []
                }
                
                # Add to buffer
                self.document_buffer.append(document)
                
                # Process buffer if full
                if len(self.document_buffer) >= self.buffer_size:
                    await self._process_buffer()
                
                logger.info(f"Successfully processed file: {url}")
            else:
                logger.error(f"Failed to process file: {url}")
                
        except Exception as e:
            logger.error(f"Error processing downloaded file {url}: {e}")

    async def _process_buffer(self):
        """Process the document buffer and upload to vector database."""
        if not self.document_buffer:
            return
        
        try:
            logger.info(f"Processing buffer with {len(self.document_buffer)} documents")
            
            # Generate embeddings
            embedded_docs = self.embedder.generate_embeddings(self.document_buffer)
            
            if embedded_docs:
                # Upload to Pinecone
                upload_result = self.embedder.upload_to_pinecone(embedded_docs)
                
                if upload_result.get("success"):
                    logger.info(f"Successfully uploaded {upload_result.get('successful_uploads', 0)} documents")
                else:
                    logger.error(f"Upload failed: {upload_result.get('error', 'Unknown error')}")
            
            # Clear buffer
            self.document_buffer.clear()
            
        except Exception as e:
            logger.error(f"Error processing buffer: {e}")

    async def finalize(self):
        """Finalize processing by handling any remaining documents in buffer."""
        if self.document_buffer:
            await self._process_buffer()
        
        # Clean up temp directories
        try:
            import shutil
            shutil.rmtree(self.temp_dir)
            logger.info("Cleaned up temporary directories")
        except Exception as e:
            logger.warning(f"Error cleaning up temp directories: {e}")

    def _extract_title_from_html(self, html_content: str) -> str:
        """Extract title from HTML content."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            title_tag = soup.find('title')
            if title_tag:
                return title_tag.get_text().strip()
            return "Untitled Document"
        except Exception:
            return "Untitled Document"

    async def run_streaming_crawl(self):
        """Run the complete streaming crawl and index process."""
        try:
            logger.info("Starting streaming crawl and index process")
            
            # Create crawler
            crawler = WebCrawler(self.config.crawler)
            
            # Set up callbacks
            crawler.on_page_callback = self.process_html_page
            crawler.on_file_callback = self.process_downloaded_file
            
            # Run crawler
            await crawler.run()
            
            # Finalize processing
            await self.finalize()
            
            # Print stats
            crawler.print_stats()
            
            logger.info("Streaming crawl and index process completed")
            
        except Exception as e:
            logger.error(f"Error in streaming crawl: {e}")
            raise
        finally:
            # Clean up crawler
            if 'crawler' in locals():
                await crawler.close()
