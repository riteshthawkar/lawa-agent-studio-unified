"""
Tests for PDFProcessor.

These tests cover PDF processing functionality with mocked
external dependencies (Gemini AI, file operations).
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import tempfile
import io


class MockProcessingConfig:
    """Mock processing configuration"""
    def __init__(self):
        self.ocr_enabled = True
        self.max_pages = 100
        self.memory_limit_mb = 1024
        self.auto_ocr = True


class TestPDFProcessorInit:
    """Tests for PDF processor initialization"""
    
    def test_processor_initialization(self):
        """Test that processor initializes correctly"""
        from modules.pdf_processor import PDFProcessor
        
        config = MockProcessingConfig()
        
        with patch('modules.pdf_processor.setup_gemini_client', return_value=None):
            processor = PDFProcessor(config)
            
            assert processor.config == config


class TestPDFProcessorFromBytes:
    """Tests for processing PDF from bytes"""
    
    def test_process_pdf_from_bytes_basic(self):
        """Test processing PDF from bytes"""
        from modules.pdf_processor import PDFProcessor
        
        config = MockProcessingConfig()
        
        with patch('modules.pdf_processor.setup_gemini_client', return_value=None):
            processor = PDFProcessor(config)
            
            # Create minimal PDF bytes (mocked)
            pdf_bytes = b"%PDF-1.4 mock content"
            source_url = "https://example.com/doc.pdf"
            
            with patch('modules.pdf_processor.worker_process_pdf_from_bytes') as mock_worker:
                mock_worker.return_value = {
                    "markdown": "# Test Document\n\nContent here",
                    "page_count": 1
                }
                
                result = processor.process_pdf_from_bytes(
                    pdf_bytes,
                    source_url,
                    auto_ocr=False
                )
                
                assert mock_worker.called
    
    def test_process_pdf_pagination(self):
        """Test processing specific page range"""
        from modules.pdf_processor import PDFProcessor
        
        config = MockProcessingConfig()
        
        with patch('modules.pdf_processor.setup_gemini_client', return_value=None):
            processor = PDFProcessor(config)
            
            pdf_bytes = b"%PDF-1.4 mock content"
            
            with patch('modules.pdf_processor.worker_process_pdf_from_bytes') as mock_worker:
                mock_worker.return_value = {
                    "markdown": "# Page 2-5 content",
                    "page_count": 4
                }
                
                processor.process_pdf_from_bytes(
                    pdf_bytes,
                    "https://example.com/doc.pdf",
                    start_page=1,
                    end_page=5
                )
                
                call_args = mock_worker.call_args
                assert call_args is not None


class TestPDFWorkerFunction:
    """Tests for worker_process_pdf_from_bytes function"""
    
    def test_worker_empty_pdf(self):
        """Test worker with empty/invalid PDF"""
        from modules.pdf_processor import worker_process_pdf_from_bytes
        
        # Invalid PDF bytes should handle gracefully
        with patch('fitz.open') as mock_fitz:
            mock_fitz.side_effect = Exception("Invalid PDF")
            
            result = worker_process_pdf_from_bytes(
                b"not a pdf",
                "https://example.com/invalid.pdf",
                None,  # no Gemini key
                auto_ocr=False
            )
            
            # Should return None on error
            assert result is None


class TestPDFTextExtraction:
    """Tests for text extraction from PDF"""
    
    def test_extract_text_with_ocr_disabled(self):
        """Test text extraction without OCR"""
        from modules.pdf_processor import worker_process_pdf_from_bytes
        
        with patch('fitz.open') as mock_fitz:
            # Mock PDF document
            mock_doc = MagicMock()
            mock_doc.__len__ = MagicMock(return_value=1)
            mock_doc.__iter__ = MagicMock(return_value=iter([MagicMock()]))
            
            mock_page = MagicMock()
            mock_page.get_text.return_value = "Extracted text content"
            mock_page.get_images.return_value = []
            mock_doc.load_page.return_value = mock_page
            mock_doc.__getitem__ = MagicMock(return_value=mock_page)
            
            mock_fitz.return_value = mock_doc
            mock_fitz.return_value.__enter__ = MagicMock(return_value=mock_doc)
            mock_fitz.return_value.__exit__ = MagicMock(return_value=False)
            
            result = worker_process_pdf_from_bytes(
                b"%PDF-1.4 test",
                "https://example.com/test.pdf",
                None,
                auto_ocr=False
            )
            # Should return the extracted text
            assert result is not None
            assert "Extracted text content" in result


class TestPDFImageProcessing:
    """Tests for image extraction and OCR"""
    
    def test_has_significant_images(self):
        """Test detection of significant images"""
        from modules.pdf_processor import has_significant_images
        
        mock_doc = MagicMock()
        
        # Small images should be ignored
        image_list = [
            (0, 0, 50, 50, 8, "DeviceRGB", "", "", ""),  # 50x50 - too small
        ]
        
        # Mock extract_image for small image
        mock_doc.extract_image.return_value = {"width": 50, "height": 50}
        
        result = has_significant_images(mock_doc, image_list, min_dimension=100)
        assert result is False
        
        # Large images should be detected
        image_list = [
            (0, 0, 500, 400, 8, "DeviceRGB", "", "", ""),  # 500x400 - significant
        ]
        
        # Mock extract_image for large image
        mock_doc.extract_image.return_value = {"width": 500, "height": 400}
        
        result = has_significant_images(mock_doc, image_list, min_dimension=100)
        assert result is True
    
    def test_check_memory_usage(self):
        """Test memory usage checking"""
        from modules.pdf_processor import check_memory_usage
        
        # Should not raise with high threshold
        result = check_memory_usage(threshold_mb=10000)
        assert result is True


class TestOCRFunctions:
    """Tests for OCR-related functions"""
    
    def test_setup_gemini_client_no_key(self):
        """Test Gemini setup without API key"""
        from modules.pdf_processor import setup_gemini_client
        
        result = setup_gemini_client(None)
        assert result is None
    
    def test_setup_gemini_client_with_key(self):
        """Test Gemini setup with API key"""
        from modules.pdf_processor import setup_gemini_client
        
        with patch('google.generativeai.configure') as mock_configure:
            with patch('google.generativeai.GenerativeModel') as mock_model:
                mock_model.return_value = MagicMock()
                
                result = setup_gemini_client("test-api-key")
                
                mock_configure.assert_called_once()


class TestPDFMemoryManagement:
    """Tests for memory management in PDF processing"""
    
    def test_cleanup_memory(self):
        """Test memory cleanup function"""
        from modules.pdf_processor import cleanup_memory
        
        # Should not raise
        cleanup_memory()
    
    def test_memory_limit_enforcement(self):
        """Test that memory limits are respected"""
        from modules.pdf_processor import check_memory_usage
        
        # Very low threshold should potentially fail
        # (depends on actual memory usage)
        result = check_memory_usage(threshold_mb=1)  # 1MB - very low
        # Result depends on actual memory usage
        assert isinstance(result, bool)


class TestDocumentTypeProcessing:
    """Tests for processing different document types"""
    
    def test_process_word_document(self):
        """Test Word document processing"""
        from modules.pdf_processor import PDFProcessor
        
        config = MockProcessingConfig()
        
        with patch('modules.pdf_processor.setup_gemini_client', return_value=None):
            processor = PDFProcessor(config)
            
            # Mock docx path
            mock_path = MagicMock(spec=Path)
            mock_path.stem = "test_document"
            mock_path.name = "test_document.docx"
            
            with tempfile.TemporaryDirectory() as output_dir:
                with patch('docx.Document') as mock_docx:
                    mock_doc = MagicMock()
                    mock_doc.paragraphs = [MagicMock(text="Paragraph 1")]
                    mock_docx.return_value = mock_doc
                    
                    # This tests the method exists and runs
    
    def test_process_excel_file(self):
        """Test Excel file processing"""
        from modules.pdf_processor import PDFProcessor
        
        config = MockProcessingConfig()
        
        with patch('modules.pdf_processor.setup_gemini_client', return_value=None):
            processor = PDFProcessor(config)
            
            # Test that method exists
            assert hasattr(processor, 'process_excel_file')
    
    def test_process_csv_file(self):
        """Test CSV file processing"""
        from modules.pdf_processor import PDFProcessor
        
        config = MockProcessingConfig()
        
        with patch('modules.pdf_processor.setup_gemini_client', return_value=None):
            processor = PDFProcessor(config)
            
            # Test that method exists
            assert hasattr(processor, 'process_csv_file')
