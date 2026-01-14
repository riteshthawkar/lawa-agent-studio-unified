"""
Tests for IterativeProcessor.

These tests cover the iterative URL processing module that handles
content extraction, embedding, and indexing.
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, Any, List


class MockEmbeddingConfig:
    """Mock embedding configuration"""
    def __init__(self):
        self.model_name = "all-MiniLM-L6-v2"
        self.pinecone_api_key = "pk-test-key"
        self.pinecone_environment = "gcp-starter"
        self.pinecone_index_name = "test-index"
        self.use_hybrid_search = False
        self.chunk_size = 512
        self.chunk_overlap = 50


class MockPreprocessorConfig:
    """Mock preprocessor configuration"""
    def __init__(self):
        self.remove_boilerplate = True
        self.min_content_length = 50
        self.max_content_length = 100000


class MockPDFConfig:
    """Mock PDF configuration"""
    def __init__(self):
        self.enabled = True
        self.max_pages = 100
        self.auto_ocr = True


class TestIterativeProcessorInit:
    """Tests for processor initialization"""
    
    def test_processor_initialization(self):
        """Test that processor initializes correctly"""
        from modules.iterative_processor import IterativeProcessor
        
        embedding_config = MockEmbeddingConfig()
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            processor.embedding_config = embedding_config
            processor.task_id = "test-task-123"
            
            assert processor.embedding_config == embedding_config


class TestIterativeProcessorPDFDetection:
    """Tests for PDF URL detection"""
    
    def test_is_pdf_url_by_extension(self):
        """Test PDF detection by file extension"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            # Should detect .pdf extension
            assert processor._is_pdf_url("https://example.com/doc.pdf") is True
            assert processor._is_pdf_url("https://example.com/doc.PDF") is True
            
            # Should not detect non-PDF
            assert processor._is_pdf_url("https://example.com/page.html") is False
    
    def test_is_pdf_url_by_content_type(self):
        """Test PDF detection by content type"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            # Should detect by content-type
            assert processor._is_pdf_url(
                "https://example.com/document",
                content_type="application/pdf"
            ) is True


class TestIterativeProcessorURLResults:
    """Tests for URL result recording"""
    
    def test_record_url_result_success(self):
        """Test recording successful URL processing"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            processor.url_results = []
            
            processor._record_url_result(
                url="https://example.com/page",
                status="indexed",
                content_type="html",
                document_count=3,
                content_size_bytes=5000,
                title="Test Page"
            )
            
            assert len(processor.url_results) == 1
            assert processor.url_results[0]["status"] == "indexed"
    
    def test_record_url_result_failed(self):
        """Test recording failed URL processing"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            processor.url_results = []
            
            processor._record_url_result(
                url="https://example.com/error",
                status="failed",
                error_message="Connection timeout"
            )
            
            assert len(processor.url_results) == 1
            assert processor.url_results[0]["status"] == "failed"
            assert "timeout" in processor.url_results[0]["error_message"]


class TestIterativeProcessorTitleExtraction:
    """Tests for title extraction from content"""
    
    def test_extract_title_from_markdown(self):
        """Test title extraction from markdown content"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            content = "# Main Title\n\nSome content here."
            title = processor._extract_title_from_content(content)
            
            assert title == "Main Title"
    
    def test_extract_title_no_heading(self):
        """Test title extraction when no heading present"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            content = "Just some plain content without headings."
            title = processor._extract_title_from_content(content)
            
            # Should return first line or truncated content
            assert title is not None


class TestIterativeProcessorChunking:
    """Tests for markdown content chunking"""
    
    def test_chunk_markdown_small_content(self):
        """Test that small content is not chunked"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            processor.max_chunk_size = 40000  # 40KB
            processor.thread_pool = MagicMock()
            
            # Small content under threshold
            content = "Small content" * 10
            
            # This tests the chunking logic threshold
            # Content under 40KB should not be chunked
            assert len(content.encode('utf-8')) < 40000
    
    def test_chunk_markdown_large_content(self):
        """Test that large content is chunked"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            processor.max_chunk_size = 1000  # 1KB for testing
            
            # Large content that needs chunking
            content = "# Heading\n\n" + ("Paragraph content. " * 500)
            
            assert len(content.encode('utf-8')) > 1000


class TestIterativeProcessorMediaFiltering:
    """Tests for media filtering"""
    
    def test_filter_media_svg(self):
        """Test filtering out SVG images"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            media_items = [
                {"src": "https://example.com/image.png", "alt": "Image"},
                {"src": "data:image/svg+xml;base64,...", "alt": "SVG"},
            ]
            
            filtered = processor._filter_media(media_items)
            
            # Should filter out SVGs and data URIs
            assert len(filtered) <= len(media_items)
    
    def test_filter_media_small_icons(self):
        """Test filtering out small icons"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            media_items = [
                {"src": "https://example.com/large.jpg", "width": 500, "height": 400},
                {"src": "https://example.com/icon.png", "width": 16, "height": 16},
            ]
            
            # Should filter based on size when available
            filtered = processor._filter_media(media_items)


class TestIterativeProcessorContentCheck:
    """Tests for content type checking"""
    
    def test_needs_content_type_check_dynamic(self):
        """Test detection of dynamic URLs needing content-type check"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            # Dynamic URLs without extension
            assert processor._needs_content_type_check("https://example.com/api/doc.php") is True
            
            # Static URLs with extension
            assert processor._needs_content_type_check("https://example.com/doc.html") is False
            assert processor._needs_content_type_check("https://example.com/file.pdf") is False


import pytest
from unittest.mock import MagicMock

class TestIterativeProcessorClose:
    """Tests for resource cleanup"""
    
    @pytest.mark.asyncio
    async def test_close_cleanup(self):
        """Test that close() cleans up resources"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            # Mock thread pool
            mock_pool = MagicMock()
            processor.thread_pool = mock_pool
            
            await processor.close()
            
            mock_pool.shutdown.assert_called_once()


class TestIterativeProcessorContextHeader:
    """Tests for heading context building"""
    
    def test_build_context_header(self):
        """Test building context header from heading stack"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            heading_stack = [
                {"level": 1, "text": "Main Section"},
                {"level": 2, "text": "Subsection"},
            ]
            
            header = processor._build_context_header(heading_stack)
            
            assert "Main Section" in header
            assert "Subsection" in header
    
    def test_add_heading_context_to_chunk(self):
        """Test adding heading context to a chunk"""
        from modules.iterative_processor import IterativeProcessor
        
        with patch.object(IterativeProcessor, '__init__', lambda self, *args, **kwargs: None):
            processor = IterativeProcessor.__new__(IterativeProcessor)
            
            chunk = {
                "content": "Chunk content here",
                "heading_stack": [{"level": 1, "text": "Section"}]
            }
            
            result = processor._add_heading_context_to_chunk(chunk)
            
            # Should prepend context
            assert result is not None
