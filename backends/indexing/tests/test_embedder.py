"""
Tests for DocumentEmbedder.

These tests cover the embedding generation and Pinecone vector
database operations with mocked external dependencies.
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, Any, List
import numpy as np


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
        self.include_summary = True
        self.include_full_content = True
        self.max_content_size_bytes = 100000


class TestDocumentEmbedderInit:
    """Tests for embedder initialization"""
    
    @patch('modules.embedder._model_cache', {})
    def test_embedder_initialization(self):
        """Test that embedder initializes correctly"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            assert embedder.config == config
    
    @patch('modules.embedder._model_cache', {})
    def test_embedder_model_caching(self):
        """Test that models are cached to prevent reloading"""
        from modules.embedder import DocumentEmbedder, _model_cache
        
        # Verify cache is used
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            # _model_cache is populated by _get_cached_model
            assert isinstance(_model_cache, dict)


class TestDocumentEmbedderChunking:
    """Tests for content chunking"""
    
    def test_chunk_document_basic(self):
        """Test basic document chunking"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            text = "This is a test document. " * 100  # Long text
            chunks = embedder.chunk_document(text, max_chunk_size=200, overlap_size=50)
            
            assert len(chunks) > 1
            chunks = embedder.chunk_document(text, max_chunk_size=10, overlap_size=2)
            
            assert len(chunks) > 1
            for chunk in chunks:
                assert len(chunk.split()) <= 10
    
    def test_chunk_document_small_content(self):
        """Test that small content is not chunked"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            text = "Small document"
            chunks = embedder.chunk_document(text, max_chunk_size=500)
            
            assert len(chunks) == 1
            assert chunks[0] == text


class TestDocumentEmbedderContentSize:
    """Tests for content size checking"""
    
    def test_check_content_size_within_limit(self):
        """Test content within size limit"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            content = "Small content"
            result = embedder._check_content_size(content, max_size_bytes=1000)
            
            assert result is True
    
    def test_check_content_size_exceeds_limit(self):
        """Test content exceeding size limit"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            content = "A" * 50000  # 50KB - exceeds 35KB default
            result = embedder._check_content_size(content)
            
            assert result is False
    
    def test_truncate_content_safely(self):
        """Test safe content truncation"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            content = "This is a long document. " * 1000
            truncated = embedder._truncate_content_safely(content, max_size_bytes=1000)
            
            # Truncation adds "..." so strictly it might be 1003 bytes
            assert len(truncated.encode('utf-8')) <= 1003


class TestDocumentEmbedderEmbeddings:
    """Tests for embedding generation"""
    
    def test_generate_embeddings(self):
        """Test embedding generation for documents"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            embedder.embedding_model = MagicMock()
            embedder.embedding_model.encode.return_value = np.array([[0.1] * 384])
            
            documents = [{"content": "Test document", "url": "https://example.com"}]
            
            with patch.object(embedder, 'format_document_for_embedding', return_value="Test document"):
                embeddings = embedder.generate_embeddings(documents)
                
                assert len(embeddings) == 1


class TestDocumentEmbedderPinecone:
    """Tests for Pinecone operations"""
    
    def test_prepare_for_pinecone(self):
        """Test preparing documents for Pinecone upload"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            embedder.embedding_model = MagicMock()
            embedder.embedding_model.encode.return_value = np.array([[0.1] * 384])
            
            documents = [
                {
                    "content": "Test document",
                    "url": "https://example.com",
                    "title": "Test"
                }
            ]
            
            with patch.object(embedder, 'generate_embeddings', return_value=np.array([[0.1] * 384])):
                prepared = embedder.prepare_for_pinecone(documents)
                
                assert len(prepared) == 1
                assert "id" in prepared[0]
                assert "values" in prepared[0]
    
    @pytest.mark.asyncio
    async def test_index_documents_memory(self):
        """Test indexing documents from memory"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            embedder.embedding_model = MagicMock()
            embedder.embedding_model.encode.return_value = np.array([[0.1] * 384])
            embedder.pinecone_client = MagicMock()
            embedder.pinecone_index = MagicMock()
            embedder.pinecone_index.upsert = MagicMock()
            
            documents = [
                {
                    "content": "Test document",
                    "url": "https://example.com",
                    "title": "Test"
                }
            ]
            
            namespace = "test_namespace"
            
            with patch.object(embedder, 'prepare_for_pinecone', return_value=[{"id": "1", "values": [0.1] * 384}]):
                result = await embedder.index_documents_memory(
                    documents,
                    namespace=namespace
                )


class TestDocumentEmbedderSearch:
    """Tests for search functionality"""
    
    def test_search_similar(self):
        """Test searching for similar documents"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            embedder.embedding_model = MagicMock()
            embedder.embedding_model.encode.return_value = np.array([[0.1] * 384])
            embedder.pinecone_index = MagicMock()
            embedder.pinecone_index.query.return_value = MagicMock(
                matches=[
                    MagicMock(id="1", score=0.9, metadata={"content": "Doc 1"}),
                    MagicMock(id="2", score=0.8, metadata={"content": "Doc 2"})
                ]
            )
            
            results = embedder.search_similar("test query", top_k=5)
            
            assert embedder.pinecone_index.query.called


class TestDocumentEmbedderFormats:
    """Tests for document formatting"""
    
    def test_format_document_for_embedding(self):
        """Test formatting document for embedding"""
        from modules.embedder import DocumentEmbedder
        
        config = MockEmbeddingConfig()
        
        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(config)
            
            doc = {
                "document_title": "Test Title",
                "page_content": "Test content here",
                "url": "https://example.com"
            }
            
            formatted = embedder.format_document_for_embedding(doc)
            
            assert "Test Title" in formatted
            assert "Test content" in formatted
