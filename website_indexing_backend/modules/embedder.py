"""
Embedding and vector database module.
Handles document embedding generation and Pinecone vector database operations.
"""

import os
import json
import uuid
import hashlib
import ssl
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import threading
import time
import asyncio
import aiohttp
from aiolimiter import AsyncLimiter

from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
from pinecone_text.sparse import BM25Encoder

from .config import EmbeddingConfig
from .markdown_splitter import MarkdownSplitter

logger = logging.getLogger(__name__)

# Global model cache to prevent multiple loading of the same model
_model_cache = {}
_bm25_cache = None
_model_cache_lock = threading.Lock()


class DocumentEmbedder:
    """Handles document embedding and vector database operations."""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.embedding_model = None
        self.pinecone_client = None
        self.pinecone_index = None
        self.bm25_encoder = None
        self.corpus = []  # Store corpus for BM25
        self._bm25_fitted = False
        self.markdown_splitter = MarkdownSplitter(
            max_chunk_size=2000,  # Words per chunk
            overlap_size=200,     # Overlap between chunks
            preserve_atomic_blocks=True,
            include_all_headings=True
        )
        self._setup_models()

    def _setup_models(self):
        """Setup embedding model and Pinecone client."""
        try:
            # Setup embedding model with caching
            self.embedding_model = self._get_cached_model(self.config.embed_model)
            logger.info(f"Embedding model loaded: {self.config.embed_model}")
            
            # Setup BM25 encoder with caching
            self.bm25_encoder = self._get_cached_bm25_encoder()
            
            # Setup Pinecone
            pinecone_api_key = os.getenv("PINECONE_API_KEY")
            if pinecone_api_key:
                self.pinecone_client = Pinecone(api_key=pinecone_api_key)
                self.pinecone_index = self.pinecone_client.Index(self.config.pinecone_index)
                logger.info(f"Pinecone client connected to index: {self.config.pinecone_index}")
            else:
                logger.warning("PINECONE_API_KEY not found, vector database operations will be limited")
                
        except Exception as e:
            logger.error(f"Error setting up embedding models: {e}")

    def _get_cached_model(self, model_name: str) -> SentenceTransformer:
        """Get or create a cached embedding model to prevent multiple loading."""
        with _model_cache_lock:
            if model_name not in _model_cache:
                logger.info(f"Loading embedding model: {model_name}")
                _model_cache[model_name] = SentenceTransformer(model_name)
                logger.info(f"Embedding model cached: {model_name}")
            else:
                logger.info(f"Using cached embedding model: {model_name}")
            return _model_cache[model_name]

    def _get_cached_bm25_encoder(self) -> Optional[BM25Encoder]:
        """Get or create a cached BM25 encoder to prevent multiple loading."""
        global _bm25_cache
        with _model_cache_lock:
            # Allow disabling sparse embedding for stability/perf
            if os.getenv("DISABLE_SPARSE", "false").lower() == "true":
                logger.info("Sparse embedding disabled via DISABLE_SPARSE env var")
                return None
            if _bm25_cache is None:
                try:
                    logger.info("Loading BM25 encoder")
                    result: Dict[str, Any] = {"encoder": None, "error": None}

                    def init_encoder():
                        try:
                            result["encoder"] = BM25Encoder.default()
                        except Exception as e:
                            result["error"] = e

                    t = threading.Thread(target=init_encoder, daemon=True)
                    t.start()
                    t.join(timeout=int(os.getenv("BM25_INIT_TIMEOUT_SEC", "10")))

                    if t.is_alive():
                        logger.warning("BM25 encoder initialization timed out; proceeding without sparse vectors")
                        _bm25_cache = None
                    elif result["error"] is not None:
                        logger.warning(f"Failed to initialize BM25 encoder: {result['error']}")
                        _bm25_cache = None
                    else:
                        _bm25_cache = result["encoder"]
                        logger.info("BM25 encoder initialized and cached")
                except Exception as e:
                    logger.warning(f"Failed to initialize BM25 encoder: {e}")
                    _bm25_cache = None
            else:
                logger.info("Using cached BM25 encoder")
            return _bm25_cache

    def _check_content_size(self, content: str, max_size_bytes: int = 35000) -> bool:
        """
        Check if content fits within Pinecone's metadata size limit.
        
        Args:
            content (str): Content to check
            max_size_bytes (int): Maximum size in bytes (default 35KB for safety)
            
        Returns:
            bool: True if content fits within size limit
        """
        try:
            content_bytes = len(content.encode('utf-8'))
            fits = content_bytes <= max_size_bytes
            if not fits:
                logger.warning(f"Content too large: {content_bytes} bytes (limit: {max_size_bytes})")
            return fits
        except Exception as e:
            logger.error(f"Error checking content size: {e}")
            return False

    def _truncate_content_safely(self, content: str, max_size_bytes: int = 35000) -> str:
        """
        Safely truncate content to fit within size limits while preserving word boundaries.
        
        Args:
            content (str): Content to truncate
            max_size_bytes (int): Maximum size in bytes
            
        Returns:
            str: Truncated content
        """
        try:
            if self._check_content_size(content, max_size_bytes):
                return content
            
            # Binary search to find the maximum safe length
            left, right = 0, len(content)
            safe_content = ""
            
            while left <= right:
                mid = (left + right) // 2
                test_content = content[:mid]
                
                if self._check_content_size(test_content, max_size_bytes):
                    safe_content = test_content
                    left = mid + 1
                else:
                    right = mid - 1
            
            # Try to end at a word boundary
            if safe_content and not safe_content.endswith(' '):
                last_space = safe_content.rfind(' ')
                if last_space > len(safe_content) * 0.8:  # Only if we don't lose too much
                    safe_content = safe_content[:last_space]
            
            logger.info(f"Content truncated from {len(content)} to {len(safe_content)} characters")
            return safe_content + "..." if safe_content != content else safe_content
            
        except Exception as e:
            logger.error(f"Error truncating content: {e}")
            return content[:1000]  # Fallback to first 1000 chars

    def _chunk_content_with_markdown_splitter(self, content: str, source_url: str) -> List[Dict[str, Any]]:
        """
        Chunk content using MarkdownSplitter for better semantic chunking.
        
        Args:
            content (str): Content to chunk
            source_url (str): Source URL for metadata
            
        Returns:
            List[Dict]: List of chunk dictionaries with metadata
        """
        try:
            # Use MarkdownSplitter for intelligent chunking
            chunks = self.markdown_splitter.split_markdown(content)
            
            if not chunks:
                logger.warning("MarkdownSplitter returned no chunks")
                return []
            
            # Convert chunks to our format
            chunk_docs = []
            for i, chunk in enumerate(chunks):
                chunk_doc = {
                    "id": f"chunk_{i}",
                    "text": chunk,
                    "metadata": {
                        "url": source_url,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "chunk_type": "markdown_chunk"
                    }
                }
                chunk_docs.append(chunk_doc)
            
            logger.info(f"Content chunked into {len(chunk_docs)} chunks using MarkdownSplitter")
            return chunk_docs
            
        except Exception as e:
            logger.error(f"Error chunking content with MarkdownSplitter: {e}")
            # Fallback to simple chunking
            return self._fallback_chunk_content(content, source_url)

    def _fallback_chunk_content(self, content: str, source_url: str) -> List[Dict[str, Any]]:
        """
        Fallback chunking method if MarkdownSplitter fails.
        
        Args:
            content (str): Content to chunk
            source_url (str): Source URL for metadata
            
        Returns:
            List[Dict]: List of chunk dictionaries
        """
        try:
            # Simple word-based chunking
            words = content.split()
            chunk_size = 1500  # Words per chunk
            overlap = 150      # Overlap between chunks
            
            chunks = []
            for i in range(0, len(words), chunk_size - overlap):
                chunk_words = words[i:i + chunk_size]
                chunk_text = ' '.join(chunk_words)
                
                chunk_doc = {
                    "id": f"fallback_chunk_{i//(chunk_size - overlap)}",
                    "text": chunk_text,
                    "metadata": {
                        "url": source_url,
                        "chunk_index": i//(chunk_size - overlap),
                        "total_chunks": (len(words) + chunk_size - overlap - 1) // (chunk_size - overlap),
                        "chunk_type": "fallback_chunk"
                    }
                }
                chunks.append(chunk_doc)
            
            logger.info(f"Content chunked into {len(chunks)} chunks using fallback method")
            return chunks
            
        except Exception as e:
            logger.error(f"Error in fallback chunking: {e}")
            return []

    def _process_content_for_pinecone(self, content: str, source_url: str) -> List[Dict[str, Any]]:
        """
        Process content to fit Pinecone constraints with intelligent chunking.
        
        Args:
            content (str): Content to process
            source_url (str): Source URL for metadata
            
        Returns:
            List[Dict]: List of processed content chunks ready for indexing
        """
        try:
            # Check if content fits within size limit
            if self._check_content_size(content):
                # Content fits, return as single chunk
                return [{
                    "id": f"single_{hashlib.sha1(source_url.encode()).hexdigest()[:12]}",
                    "text": content,
                    "metadata": {
                        "url": source_url,
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "chunk_type": "single"
                    }
                }]
            else:
                # Content is too large, chunk it
                logger.info(f"Content exceeds size limit, chunking content from {source_url}")
                return self._chunk_content_with_markdown_splitter(content, source_url)
                
        except Exception as e:
            logger.error(f"Error processing content for Pinecone: {e}")
            return []

    def _generate_sparse_embedding(self, text: str) -> Dict[str, List]:
        """Generate sparse embedding using Pinecone Text BM25Encoder."""
        if not self.bm25_encoder:
            logger.debug("BM25 encoder not available, skipping sparse embedding")
            return {"indices": [], "values": []}
        
        try:
            # Use the official Pinecone Text BM25Encoder
            sparse_vector = self.bm25_encoder.encode_documents(text)
            return sparse_vector
        except Exception as e:
            logger.warning(f"Error generating sparse embedding: {e}")
            return {"indices": [], "values": []}

    def _update_corpus(self, text: str):
        """Update the corpus for BM25 model."""
        self.corpus.append(text)
        # Fit once when we have enough documents to build a useful corpus
        if self.bm25_encoder and not self._bm25_fitted:
            try:
                min_docs = int(os.getenv("BM25_MIN_DOCS", "5"))
                if len(self.corpus) >= min_docs:
                    self.bm25_encoder.fit(self.corpus)
                    self._bm25_fitted = True
                    logger.info(f"BM25 encoder fitted with {len(self.corpus)} documents")
            except Exception as e:
                logger.error(f"Error fitting BM25 encoder: {e}")

    def format_document_for_embedding(self, doc: Dict[str, Any]) -> str:
        """Format a document for embedding generation."""
        formatted_text = f"TITLE: {doc.get('document_title', 'Unknown Title')}\n"
        
        if doc.get('document_type'):
            formatted_text += f"TYPE: {doc.get('document_type')}\n"
        
        if doc.get('document_date'):
            formatted_text += f"DATE: {doc.get('document_date')}\n"
        
        if self.config.include_summary:
            if doc.get('detailed_summary'):
                formatted_text += f"\nSUMMARY:\n{doc.get('detailed_summary')}\n"
            
            # Add key facts
            key_facts = doc.get('key_facts', [])
            if key_facts:
                formatted_text += "\nKEY FACTS:\n"
                for fact in key_facts:
                    formatted_text += f"- {fact}\n"
            
            # Add keywords
            keywords = doc.get('keywords', [])
            if keywords:
                formatted_text += f"\nKEYWORDS: {', '.join(keywords)}\n"
        
        if self.config.include_full_content:
            full_content = doc.get('page_content', '')
            formatted_text += f"\n\nFULL CONTENT:\n{full_content}\n"
        
        return formatted_text

    def generate_embeddings(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate embeddings for a list of documents."""
        if not self.embedding_model:
            logger.error("Embedding model not available")
            return []
        
        logger.info(f"Generating embeddings for {len(documents)} documents")
        
        formatted_docs = []
        for i, doc in enumerate(documents):
            try:
                formatted_text = self.format_document_for_embedding(doc)
                
                formatted_docs.append({
                    "id": doc.get('source_document_name', f"doc_{i}"),
                    "text": formatted_text,
                    "metadata": {
                        "document_title": doc.get('document_title'),
                        "document_type": doc.get('document_type'),
                        "document_date": doc.get('document_date'),
                        "document_source": doc.get('page_source'),
                        "key_facts": doc.get('key_facts'),
                        "entities": doc.get('entities'),
                        "keywords": doc.get('keywords'),
                        "document_summary": doc.get('detailed_summary'),
                    }
                })
            except Exception as e:
                logger.error(f"Error formatting document {i}: {e}")
        
        # Generate embeddings
        texts = [doc["text"] for doc in formatted_docs]
        embeddings = self.embedding_model.encode(texts, show_progress_bar=True)
        
        # Add embeddings to documents
        for i, doc in enumerate(formatted_docs):
            doc["values"] = embeddings[i].tolist()
        
        logger.info(f"Generated embeddings for {len(formatted_docs)} documents")
        return formatted_docs

    def chunk_document(self, text: str, max_chunk_size: int = 2000, overlap_size: int = 200) -> List[str]:
        """Split a document into chunks for better embedding."""
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), max_chunk_size - overlap_size):
            chunk = ' '.join(words[i:i + max_chunk_size])
            chunks.append(chunk)
            
            if i + max_chunk_size >= len(words):
                break
        
        return chunks

    def prepare_for_pinecone(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare documents for Pinecone upload."""
        pinecone_docs = []
        
        for doc in documents:
            try:
                # Generate unique ID
                doc_id = str(uuid.uuid4())
                
                # Prepare metadata
                metadata = doc.get("metadata", {})
                metadata["page_id"] = doc.get("id", doc_id)
                metadata["page_source"] = metadata.get("document_source", "")
                
                # Handle None values
                if metadata.get("document_date") is None:
                    metadata["document_date"] = "Not Given"
                
                # Convert complex objects to JSON strings
                for key in ["entities", "key_facts", "keywords"]:
                    if key in metadata and metadata[key] is not None:
                        metadata[key] = json.dumps(metadata[key])
                
                pinecone_doc = {
                    "id": doc_id,
                    "values": doc.get("values", []),
                    "metadata": metadata
                }
                
                pinecone_docs.append(pinecone_doc)
                
            except Exception as e:
                logger.error(f"Error preparing document for Pinecone: {e}")
        
        return pinecone_docs

    def upload_to_pinecone(self, documents: List[Dict[str, Any]], batch_size: int = 50) -> Dict[str, Any]:
        """Upload documents to Pinecone vector database."""
        if not self.pinecone_index:
            logger.error("Pinecone index not available")
            return {"success": False, "error": "Pinecone not configured"}
        
        logger.info(f"Uploading {len(documents)} documents to Pinecone")
        
        # Prepare documents for Pinecone
        pinecone_docs = self.prepare_for_pinecone(documents)
        
        # Upload in batches
        successful_uploads = 0
        failed_uploads = 0
        failed_batches = []
        
        for i in range(0, len(pinecone_docs), batch_size):
            batch = pinecone_docs[i:i + batch_size]
            
            try:
                self.pinecone_index.upsert(vectors=batch)
                successful_uploads += len(batch)
                logger.info(f"Uploaded batch {i//batch_size + 1}: {len(batch)} documents")
                
            except Exception as e:
                logger.error(f"Failed to upload batch {i//batch_size + 1}: {e}")
                failed_uploads += len(batch)
                failed_batches.append(batch)
        
        # Retry failed batches individually
        if failed_batches:
            logger.info("Retrying failed uploads individually")
            for batch in failed_batches:
                for doc in batch:
                    try:
                        self.pinecone_index.upsert(vectors=[doc])
                        successful_uploads += 1
                    except Exception as e:
                        logger.error(f"Failed to upload individual document: {e}")
                        failed_uploads += 1
        
        result = {
            "success": True,
            "total_documents": len(documents),
            "successful_uploads": successful_uploads,
            "failed_uploads": failed_uploads
        }
        
        logger.info(f"Upload complete: {successful_uploads} successful, {failed_uploads} failed")
        return result

    def process_documents(self, input_file: str, output_file: Optional[str] = None) -> Dict[str, Any]:
        """Process documents from JSON file and upload to Pinecone."""
        try:
            # Load documents
            with open(input_file, 'r', encoding='utf-8') as f:
                documents = json.load(f)
            
            logger.info(f"Loaded {len(documents)} documents from {input_file}")
            
            # Generate embeddings
            embedded_docs = self.generate_embeddings(documents)
            
            if not embedded_docs:
                return {"success": False, "error": "No documents processed"}
            
            # Save formatted documents if output file specified
            if output_file:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(embedded_docs, f, ensure_ascii=False, indent=2)
                logger.info(f"Saved formatted documents to {output_file}")
            
            # Upload to Pinecone
            upload_result = self.upload_to_pinecone(embedded_docs)
            
            return {
                "success": True,
                "documents_processed": len(embedded_docs),
                "upload_result": upload_result
            }
            
        except Exception as e:
            logger.error(f"Error processing documents: {e}")
            return {"success": False, "error": str(e)}

    async def index_documents_memory(self, documents: List[Dict[str, Any]], namespace: Optional[str] = None, batch_size: int = 100) -> int:
        """Index documents directly from memory with intelligent chunking for large content."""
        try:
            if not self.pinecone_index:
                logger.error("Pinecone index not available")
                return 0
            
            if not documents:
                return 0
            
            # Process all documents with size checking and chunking
            all_processed_docs = []
            
            for doc in documents:
                try:
                    text_content = doc["text"]
                    source_url = doc["metadata"].get("url", "")
                    
                    # Process content for Pinecone (handles chunking if needed)
                    processed_chunks = self._process_content_for_pinecone(text_content, source_url)
                    all_processed_docs.extend(processed_chunks)
                    
                except Exception as e:
                    logger.error(f"Error processing document {doc.get('id', 'unknown')}: {e}")
                    continue
            
            if not all_processed_docs:
                logger.warning("No valid processed documents to index")
                return 0
            
            logger.info(f"Processing {len(all_processed_docs)} document chunks for indexing")
            
            # Prepare vectors for indexing with batch embedding generation
            vectors = []
            logger.info(f"Generating embeddings for {len(all_processed_docs)} documents in batches")
            
            # Process embeddings in very small batches for Apple Silicon MPS memory constraints
            embedding_batch_size = min(batch_size, 5)  # Reduced to 5 for MPS memory safety
            for i in range(0, len(all_processed_docs), embedding_batch_size):
                batch_docs = all_processed_docs[i:i + embedding_batch_size]
                
                # Prepare texts for embedding (reasonable length check only)
                batch_texts = []
                for doc in batch_docs:
                    text = doc["text"]
                    # Only truncate extremely large texts (most embedding models handle up to 512 tokens well)
                    if len(text) > 50000:  # Very generous limit - 50K characters
                        text = text[:50000] + "..."
                        logger.warning(f"Truncated very large text for embedding: {len(doc['text'])} -> 50000 chars")
                    batch_texts.append(text)
                
                # Process embeddings one document at a time to avoid MPS memory issues
                logger.debug(f"Generating embeddings individually for batch {i//embedding_batch_size + 1}/{(len(all_processed_docs) + embedding_batch_size - 1)//embedding_batch_size}")
                batch_embeddings = []
                
                for idx, single_text in enumerate(batch_texts):
                    try:
                        logger.debug(f"Embedding document {idx + 1}/{len(batch_texts)} in current batch")
                        single_embedding = self.embedding_model.encode([single_text], show_progress_bar=False)
                        batch_embeddings.append(single_embedding[0])
                        
                        # Small delay to help with MPS memory cleanup
                        if idx < len(batch_texts) - 1:  # Don't delay after the last item
                            import time
                            time.sleep(0.1)
                            
                    except Exception as embed_e:
                        logger.error(f"Error embedding single text {idx + 1}: {embed_e}")
                        # Create zero vector as fallback (get actual dimension from model)
                        try:
                            # Try to get dimension from a small test
                            test_embedding = self.embedding_model.encode(["test"], show_progress_bar=False)
                            dimension = len(test_embedding[0])
                        except:
                            dimension = 384  # Common dimension fallback
                        batch_embeddings.append([0.0] * dimension)
                
                # Process each document in the batch
                for j, doc in enumerate(batch_docs):
                    try:
                        text_content = doc["text"]
                        
                        # Update corpus for BM25
                        self._update_corpus(text_content)
                        
                        # Use pre-computed embedding
                        dense_embedding = batch_embeddings[j].tolist()
                        
                        # Generate sparse embedding
                        sparse_embedding = self._generate_sparse_embedding(text_content)
                        
                        # Bug #25-26 fix: Enhanced metadata for Pinecone with URL/media preservation
                        # CRITICAL: Pinecone has a 40KB (40,960 bytes) metadata limit per vector
                        # We must carefully manage the total size

                        # 1. Prepare base metadata fields (non-content)
                        base_metadata = {
                            "source": doc["metadata"]["url"][:500],  # Limit URL length
                            "title": doc["metadata"].get("title", "")[:200],  # Limit title
                            "chunk_index": doc["metadata"].get("chunk_index", 0),
                            "total_chunks": doc["metadata"].get("total_chunks", 1),
                        }
                        
                        # 2. Prepare extracted data (urls, images) with strict limits
                        extracted_urls = doc["metadata"].get("extracted_urls", [])
                        extracted_media = doc["metadata"].get("extracted_media", {})
                        
                        limited_urls = extracted_urls[:10] if extracted_urls else []  # Reduced to 10
                        limited_image_urls = extracted_media.get("images", [])[:3] if extracted_media else []  # Reduced to 3
                        limited_image_alts = extracted_media.get("alt_texts", [])[:3] if extracted_media else []
                        
                        base_metadata["extracted_urls"] = limited_urls
                        base_metadata["image_urls"] = limited_image_urls
                        base_metadata["image_alts"] = limited_image_alts
                        
                        # 3. Calculate remaining budget for text content
                        # Serialize base_metadata to get actual byte size
                        base_metadata_json = json.dumps(base_metadata)
                        base_size = len(base_metadata_json.encode('utf-8'))
                        
                        # Pinecone limit is 40960 bytes. Leave 1KB buffer for safety.
                        PINECONE_LIMIT = 40960
                        SAFETY_BUFFER = 1024
                        available_for_text = PINECONE_LIMIT - base_size - SAFETY_BUFFER
                        
                        if available_for_text < 500:
                            # If we're squeezed too tight, drop optional lists to free up space
                            base_metadata["extracted_urls"] = []
                            base_metadata["image_urls"] = []
                            base_metadata["image_alts"] = []
                            base_size = len(json.dumps(base_metadata).encode('utf-8'))
                            available_for_text = PINECONE_LIMIT - base_size - SAFETY_BUFFER
                        
                        # 4. Truncate content fields to fit budget
                        # Prioritize original_content (70% of budget) for citations
                        original_budget = int(available_for_text * 0.7)
                        context_budget = available_for_text - original_budget
                        
                        def truncate_to_bytes(text: str, max_bytes: int) -> str:
                            """Safely truncate text to fit within byte limit."""
                            if not text:
                                return ""
                            if max_bytes <= 0:
                                return ""
                            encoded = text.encode('utf-8')
                            if len(encoded) <= max_bytes:
                                return text
                            # Truncate and decode safely
                            truncated = encoded[:max_bytes]
                            # Find last valid UTF-8 boundary by removing partial bytes at the end
                            while truncated:
                                try:
                                    return truncated.decode('utf-8')
                                except UnicodeDecodeError:
                                    truncated = truncated[:-1]
                            return ""

                        original_content = doc["metadata"].get("original_content", "")
                        # Fallback for original_content if missing (use text)
                        if not original_content:
                             original_content = text_content

                        original_for_metadata = truncate_to_bytes(original_content, original_budget)
                        context_for_metadata = truncate_to_bytes(text_content, context_budget)
                        
                        # 5. Construct final vector
                        vector = {
                            "id": doc["id"],
                            "values": dense_embedding,
                            "metadata": {
                                **base_metadata,
                                "context": context_for_metadata,
                                "original_content": original_for_metadata,
                            }
                        }
                        
                        # Only add sparse_values if it has content
                        if sparse_embedding["indices"]:
                            vector["sparse_values"] = sparse_embedding
                        
                        vectors.append(vector)
                        
                    except Exception as e:
                        logger.error(f"Error creating vector for document {doc.get('id', 'unknown')}: {e}")
                        continue
            
            if not vectors:
                logger.warning("No valid vectors to index")
                return 0
            
            # Index vectors in smaller batches to prevent buffer overflow
            # Reduce batch size for large documents to stay under Pinecone limits
            batch_size = min(50, batch_size)  # Max 50 vectors per batch for safety
            indexed_count = 0
            
            logger.info(f"Indexing {len(vectors)} vectors in batches of {batch_size}")
            
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i + batch_size]
                try:
                    # Calculate proper batch memory estimate (not string serialization)
                    batch_memory_estimate = 0
                    for v in batch:
                        # Estimate vector memory: embeddings + metadata
                        vector_size = len(v.get('values', [])) * 4  # 4 bytes per float32
                        metadata_size = len(str(v.get('metadata', {})).encode('utf-8'))
                        sparse_size = len(v.get('sparse_values', {}).get('indices', [])) * 8  # Estimate
                        batch_memory_estimate += vector_size + metadata_size + sparse_size
                    batch_memory_estimate = batch_memory_estimate / (1024 * 1024)  # Convert to MB
                    
                    if batch_memory_estimate > 100:  # If estimated size > 100MB, split further
                        logger.warning(f"Batch too large ({batch_memory_estimate:.1f}MB), splitting into smaller chunks")
                        # Split into smaller sub-batches
                        sub_batch_size = max(1, len(batch) // 4)
                        for j in range(0, len(batch), sub_batch_size):
                            sub_batch = batch[j:j + sub_batch_size]
                            try:
                                if namespace and self.config.use_namespaces:
                                    self.pinecone_index.upsert(vectors=sub_batch, namespace=namespace)
                                    logger.info(f"Indexed sub-batch of {len(sub_batch)} vectors to namespace: {namespace}")
                                else:
                                    self.pinecone_index.upsert(vectors=sub_batch)
                                    logger.info(f"Indexed sub-batch of {len(sub_batch)} vectors to default namespace")
                                
                                indexed_count += len(sub_batch)
                            except Exception as sub_e:
                                logger.error(f"Error indexing sub-batch: {sub_e}")
                                continue
                    else:
                        # Normal batch processing
                        if namespace and self.config.use_namespaces:
                            self.pinecone_index.upsert(vectors=batch, namespace=namespace)
                            logger.info(f"Indexed batch of {len(batch)} hybrid vectors to namespace: {namespace}")
                        else:
                            self.pinecone_index.upsert(vectors=batch)
                            logger.info(f"Indexed batch of {len(batch)} hybrid vectors to default namespace")
                        
                        indexed_count += len(batch)
                        
                except Exception as e:
                    logger.error(f"Error indexing batch: {e}")
                    # Try individual vectors if batch fails due to size
                    if "buffer size" in str(e).lower() or "too large" in str(e).lower():
                        logger.info("Attempting individual vector indexing due to size error")
                        for single_vector in batch:
                            try:
                                if namespace and self.config.use_namespaces:
                                    self.pinecone_index.upsert(vectors=[single_vector], namespace=namespace)
                                else:
                                    self.pinecone_index.upsert(vectors=[single_vector])
                                indexed_count += 1
                            except Exception as single_e:
                                logger.error(f"Failed to index individual vector {single_vector.get('id', 'unknown')}: {single_e}")
                                continue
                    continue
            
            namespace_info = f" in namespace '{namespace}'" if namespace and self.config.use_namespaces else ""
            logger.info(f"Successfully indexed {indexed_count} hybrid document chunks to vector database{namespace_info}")
            return indexed_count
            
        except Exception as e:
            logger.error(f"Error indexing documents from memory: {e}")
            return 0

    def search_similar(self, query: str, top_k: int = 5, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for similar documents in Pinecone."""
        if not self.pinecone_index or not self.embedding_model:
            logger.error("Pinecone or embedding model not available")
            return []
        
        try:
            # Generate query embedding
            query_embedding = self.embedding_model.encode([query])
            
            # Search in Pinecone with optional namespace
            query_params = {
                "vector": query_embedding[0].tolist(),
                "top_k": top_k,
                "include_metadata": True
            }
            
            if namespace and self.config.use_namespaces:
                query_params["namespace"] = namespace
            
            results = self.pinecone_index.query(**query_params)
            
            return results.matches if results.matches else []
            
        except Exception as e:
            logger.error(f"Error searching similar documents: {e}")
            return []


class GeminiDocumentEmbedder:
    """Handles document embedding using Gemini API and vector database operations."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.pinecone_client = None
        self.pinecone_index = None
        self.bm25_encoder = None
        self.corpus = []  # Store corpus for BM25
        self._bm25_fitted = False
        self.markdown_splitter = MarkdownSplitter(
            max_chunk_size=2000,  # Words per chunk
            overlap_size=200,     # Overlap between chunks
            preserve_atomic_blocks=True,
            include_all_headings=True
        )
        # Rate limiter for Gemini API (default: 60 requests per minute)
        rate_limit = int(os.getenv("GEMINI_RATE_LIMIT", "60"))
        self.rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=60)
        logger.debug(f"Gemini API rate limiter initialized: {rate_limit} requests/minute")
        self._setup_models()
    
    async def initialize(self) -> bool:
        """
        Explicitly initialize models (BM25 and verify Gemini connection).
        Designed to be called at application startup with retries.
        """
        try:
            logger.info("Initializing GeminiDocumentEmbedder...")
            
            # Initialize BM25 Encoder (CPU bound, might take a moment)
            if self.bm25_encoder is None:
                self.bm25_encoder = self._get_cached_bm25_encoder()
            
            # Setup Pinecone
            if self.pinecone_client is None:
                pinecone_api_key = os.getenv("PINECONE_API_KEY")
                if pinecone_api_key:
                    logger.info(f"Connecting to Pinecone with API Key: {pinecone_api_key[:5]}... (length: {len(pinecone_api_key)})")
                    self.pinecone_client = Pinecone(api_key=pinecone_api_key)
                    
                    index_name = self.config.pinecone_index
                    logger.info(f"Attempting to connect to Pinecone Index: '{index_name}'")
                    
                    try:
                        self.pinecone_index = self.pinecone_client.Index(index_name)
                        # Verify index stats to ensure it's real
                        stats = self.pinecone_index.describe_index_stats()
                        logger.info(f"✅ Successfully connected to Pinecone index '{index_name}'. Stats: {stats}")
                    except Exception as e:
                        logger.error(f"❌ Failed to connect to Pinecone index '{index_name}': {e}")
                        self.pinecone_index = None
                else:
                    logger.warning("PINECONE_API_KEY not found, vector database operations will be limited")
            
            # Verify Gemini API connection with a dummy embedding
            # This ensures the model is "warm" and credentials are valid
            try:
                test_embedding = await self._get_gemini_embeddings(["warmup"])
                if test_embedding:
                    logger.info("✅ Gemini API connection verified successfully")
                else:
                    logger.warning("⚠️ Gemini API returned empty embedding during warmup")
            except Exception as e:
                logger.error(f"❌ Gemini API warmup failed: {e}")
                # We don't fail initialization here, as it might be a transient network issue
                # and we want the app to start.
            
            return True
        except Exception as e:
            logger.error(f"Failed to initialize GeminiDocumentEmbedder: {e}")
            return False

    def _setup_models(self):
        """Internal setup - use initialize() for explicit startup."""
        # defer actual heavy lifting to initialize() or lazy loading
        pass
    
    def _get_cached_bm25_encoder(self) -> Optional[BM25Encoder]:
        """Get or create a cached BM25 encoder to prevent multiple loading."""
        global _bm25_cache
        with _model_cache_lock:
            if _bm25_cache is None:
                logger.info("Loading BM25 encoder (this happens once)")
                try:
                    _bm25_cache = BM25Encoder.default()
                    logger.info("BM25 encoder initialized and cached")
                except Exception as e:
                    logger.error(f"Failed to initialize BM25 encoder: {e}")
                    return None
            else:
                logger.info("Using cached BM25 encoder")
            return _bm25_cache
    
    async def _get_gemini_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get embeddings from Gemini API with retry logic.
        """
        if not self.config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not found in configuration")
        
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
        headers = {
            "x-goog-api-key": self.config.gemini_api_key,
            "Content-Type": "application/json"
        }
        
        # Get embedding dimensions from config (default 3072 to match Pinecone index)
        output_dimensions = getattr(self.config, 'gemini_embedding_dimensions', 3072)

        # Create SSL context - configurable via environment variable
        # Default: verify SSL certificates (secure)
        # Create SSL context - configurable via environment variable
        # Default: verify SSL certificates (secure)
        ssl_verify = os.getenv("GEMINI_SSL_VERIFY", "true").lower() == "true"
        if ssl_verify:
            try:
                import certifi
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                logger.debug(f"Using certifi CA bundle: {certifi.where()}")
            except ImportError:
                logger.warning("certifi not found, falling back to system CA bundle (may fail on macOS)")
                ssl_context = ssl.create_default_context()
        else:
            logger.warning("SSL verification disabled for Gemini API - not recommended for production")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        embeddings = []
        max_retries = 3
        retry_delay = 1  # seconds
        
        async with aiohttp.ClientSession(connector=connector) as session:
            for text in texts:
                # Apply rate limiting before each API call
                async with self.rate_limiter:
                    # Retry loop for each text
                    for attempt in range(max_retries):
                        try:
                            content = {"parts": [{"text": text}]}

                            # Include output_dimensionality to control embedding size
                            payload = {
                                "model": "models/gemini-embedding-001",
                                "content": content,
                                "output_dimensionality": output_dimensions
                            }

                            async with session.post(url, headers=headers, json=payload) as response:
                                if response.status == 200:
                                    result = await response.json()

                                    # Handle single embedding response
                                    if "embedding" in result:
                                        embedding_data = result["embedding"]
                                        if isinstance(embedding_data, dict) and "values" in embedding_data:
                                            embeddings.append(embedding_data["values"])
                                            break  # Success, break retry loop
                                        else:
                                            logger.error(f"Unexpected embedding structure: {embedding_data}")
                                            # Non-retryable error if structure is wrong
                                    else:
                                        logger.error(f"No embedding found in response: {result}")
                                elif response.status in [429, 500, 503]:
                                    # Retryable errors
                                    if attempt < max_retries - 1:
                                        logger.warning(f"Gemini API error {response.status}, retrying ({attempt+1}/{max_retries})...")
                                        await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                                        continue
                                    else:
                                        error_text = await response.text()
                                        logger.error(f"Gemini API failed after {max_retries} retries. Status: {response.status}, Error: {error_text}")
                                        raise Exception(f"Gemini API error {response.status}: {error_text}")
                                else:
                                    # Non-retryable error
                                    error_text = await response.text()
                                    logger.error(f"Gemini API error {response.status}: {error_text}")
                                    raise Exception(f"Gemini API error {response.status}: {error_text}")

                        except Exception as e:
                            if attempt < max_retries - 1:
                                logger.warning(f"Request failed: {e}, retrying ({attempt+1}/{max_retries})...")
                                await asyncio.sleep(retry_delay * (2 ** attempt))
                            else:
                                logger.error(f"Request failed after {max_retries} retries: {e}")
                                # Raising preserves existing behavior of failing the batch
                                raise e

        return embeddings
    
    def format_document_for_embedding(self, doc: Dict[str, Any]) -> str:
        """Format a document for embedding generation."""
        # Helper to get metadata value
        metadata = doc.get('metadata', {})
        
        title = doc.get('document_title', doc.get('title', metadata.get('title', metadata.get('document_title', 'Unknown Title'))))
        url = doc.get('page_source', doc.get('url', metadata.get('url', metadata.get('page_source', 'Unknown URL'))))
        content = doc.get('page_content', doc.get('text', metadata.get('page_content', '')))
        
        formatted_text = f"TITLE: {title}\n"
        formatted_text += f"URL: {url}\n"
        formatted_text += f"CONTENT: {content}\n"
        
        # Add metadata if available
        summary = doc.get('detailed_summary', metadata.get('detailed_summary'))
        if summary:
            formatted_text += f"SUMMARY: {summary}\n"
        
        key_facts = doc.get('key_facts', metadata.get('key_facts'))
        if key_facts:
            formatted_text += f"KEY FACTS: {', '.join(key_facts)}\n"
        
        keywords = doc.get('keywords', metadata.get('keywords'))
        if keywords:
            formatted_text += f"KEYWORDS: {', '.join(keywords)}\n"
        
        return formatted_text
    
    async def generate_embeddings(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate embeddings for a list of documents using Gemini API.
        
        Also generates BM25 sparse embeddings for hybrid search.
        """
        if not documents:
            return []
        
        logger.info(f"Generating Gemini embeddings for {len(documents)} documents")
        
        try:
            # Format documents for embedding
            formatted_texts = []
            for doc in documents:
                formatted_text = self.format_document_for_embedding(doc)
                formatted_texts.append(formatted_text)
            
            # --- BM25 Sparse Embedding ---
            # Use BM25Encoder.default() which is pre-trained on MSMARCO corpus.
            # This eliminates the need to fit on custom corpus or share files between services.
            if self.bm25_encoder and not self._bm25_fitted:
                self._bm25_fitted = True  # Mark as ready (default encoder is pre-fitted)
                logger.info("Using pre-trained BM25Encoder.default() for sparse embeddings")
            
            # Get embeddings from Gemini API
            embeddings = await self._get_gemini_embeddings(formatted_texts)
            
            # Combine documents with embeddings
            results = []
            for i, doc in enumerate(documents):
                if i < len(embeddings):
                    # Extract metadata from document or its metadata dict
                    source_metadata = doc.get('metadata', {})
                    
                    # Helper function to get value from either doc or metadata
                    def get_meta(key, alt_key=None):
                        val = doc.get(key)
                        if val is None:
                            val = source_metadata.get(key)
                        if val is None and alt_key:
                            val = doc.get(alt_key)
                            if val is None:
                                val = source_metadata.get(alt_key)
                        return val

                    # Build base metadata - NOTE: original_content is added later with proper truncation
                    # page_content is intentionally excluded to avoid redundancy
                    metadata_dict = {
                        "url": get_meta("url", "page_source") or "",
                        "title": get_meta("title", "document_title") or "",
                        "document_date": get_meta("document_date"),
                        "page_source": get_meta("page_source", "url") or "",
                        "detailed_summary": get_meta("detailed_summary"),
                        "chunk_index": get_meta("chunk_index"),
                        "total_chunks": get_meta("total_chunks"),
                        "chunk_size_bytes": get_meta("chunk_size_bytes")
                    }
                    
                    # Add optional fields only if they have content
                    key_facts = get_meta("key_facts")
                    if key_facts:
                        metadata_dict["key_facts"] = key_facts

                    entities = get_meta("entities")
                    if entities:
                        metadata_dict["entities"] = entities

                    keywords = get_meta("keywords")
                    if keywords:
                        metadata_dict["keywords"] = keywords

                    # Bug fix: Include original_content for search result display
                    original_content = get_meta("original_content")
                    if original_content:
                        metadata_dict["original_content"] = original_content

                    # Bug fix: Include extracted URLs and media for citations
                    extracted_urls = get_meta("extracted_urls")
                    if extracted_urls:
                        metadata_dict["extracted_urls"] = extracted_urls

                    extracted_media = get_meta("extracted_media")
                    if extracted_media:
                        metadata_dict["extracted_media"] = extracted_media

                    # --- Generate Sparse Embedding ---
                    sparse_embedding = self._generate_sparse_embedding_for_text(formatted_texts[i])

                    result_doc = {
                        "id": doc.get("id", doc.get("source_document_name", f"doc_{i}")),
                        "text": formatted_texts[i],
                        "dense_embedding": embeddings[i],
                        "sparse_embedding": sparse_embedding,
                        "metadata": metadata_dict
                    }
                    results.append(result_doc)
            
            logger.info(f"Generated Gemini embeddings for {len(results)} documents (with sparse embeddings: {self._bm25_fitted})")
            return results
            
        except Exception as e:
            logger.error(f"Error generating Gemini embeddings: {e}")
            return []
    
    async def index_documents_memory(self, documents: List[Dict[str, Any]], namespace: Optional[str] = None, batch_size: int = 100) -> int:
        """Index documents directly from memory using Gemini embeddings."""
        try:
            logger.debug(f"Starting index_documents_memory with {len(documents)} documents")
            logger.debug(f"Namespace: {namespace}, Use namespaces: {self.config.use_namespaces}")

            if not self.pinecone_index:
                logger.error(f"Pinecone index is NOT available. Client initialized: {self.pinecone_client is not None}. Index Object: {self.pinecone_index}")
                return 0

            logger.info(f"Processing {len(documents)} document chunks for indexing")

            # Generate embeddings
            logger.debug(f"Calling generate_embeddings for {len(documents)} documents")
            embeddings_data = await self.generate_embeddings(documents)

            if not embeddings_data:
                logger.error("No embeddings generated")
                return 0

            logger.debug(f"Generated {len(embeddings_data)} embedding data objects")
            
            # Prepare vectors for Pinecone
            vectors_to_upsert = []
            for i, embedding_data in enumerate(embeddings_data):
                vector_id = embedding_data["id"]
                dense_embedding = embedding_data["dense_embedding"]
                metadata = embedding_data["metadata"]

                logger.debug(f"Processing vector {i+1}/{len(embeddings_data)}: {vector_id}")

                # Bug #27 fix: Get original content and extracted URLs/media
                original_content = metadata.get("original_content", "")
                extracted_media = metadata.get("extracted_media", {})

                # CRITICAL: Strictly enforce 40KB limit by calculating actual JSON size
                PINECONE_LIMIT = 40960
                SAFETY_BUFFER = 2048  # 2KB buffer for JSON overhead and vector ID

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

                # 1. Build base metadata without large text content
                base_metadata = {}
                for key, value in metadata.items():
                    # Skip large content fields - we'll add them after size calculation
                    if key in ("original_content", "extracted_urls", "extracted_media", "context"):
                        continue
                    if value is not None:
                        if isinstance(value, list):
                            base_metadata[key] = [str(item) for item in value if item is not None][:20]
                        elif isinstance(value, (str, int, float, bool)):
                            # Truncate long strings
                            if isinstance(value, str) and len(value) > 500:
                                value = value[:500]
                            base_metadata[key] = value
                        else:
                            base_metadata[key] = str(value)[:200]

                # 2. Add filtered images (limited to prevent size bloat)
                if extracted_media:
                    images = extracted_media.get("images", [])
                    alts = extracted_media.get("alt_texts", [])
                    
                    filtered_images = []
                    filtered_alts = []
                    for idx, img_url in enumerate(images[:10]):
                        img_str = str(img_url).lower()
                        if img_str.startswith('data:') or img_str.endswith('.svg') or img_str.endswith('.ico'):
                            continue
                        if any(x in img_str for x in ['/icon/', 'favicon']):
                            continue
                        filtered_images.append(str(img_url)[:300])  # Limit URL length
                        if idx < len(alts):
                            filtered_alts.append(str(alts[idx])[:100])  # Limit alt text
                        if len(filtered_images) >= 5:  # Cap at 5
                            break
                    
                    base_metadata["image_urls"] = filtered_images
                    base_metadata["image_alts"] = filtered_alts

                # 3. Calculate remaining budget for text content
                base_json_size = len(json.dumps(base_metadata).encode('utf-8'))
                available_for_text = PINECONE_LIMIT - base_json_size - SAFETY_BUFFER

                if available_for_text < 500:
                    # Too squeezed - drop optional fields
                    base_metadata.pop("image_urls", None)
                    base_metadata.pop("image_alts", None)
                    base_json_size = len(json.dumps(base_metadata).encode('utf-8'))
                    available_for_text = PINECONE_LIMIT - base_json_size - SAFETY_BUFFER

                # 4. Truncate original_content to fit budget
                if available_for_text > 100:
                    base_metadata["original_content"] = truncate_to_bytes(original_content, available_for_text)
                else:
                    base_metadata["original_content"] = ""

                # 5. Final validation - ensure we're under the limit
                final_size = len(json.dumps(base_metadata).encode('utf-8'))
                if final_size > PINECONE_LIMIT - 1024:
                    # Emergency truncation
                    content = base_metadata.get("original_content", "")
                    overage = final_size - (PINECONE_LIMIT - 2048)
                    if len(content) > overage:
                        base_metadata["original_content"] = truncate_to_bytes(content, len(content.encode('utf-8')) - overage - 500)
                    else:
                        base_metadata["original_content"] = ""

                cleaned_metadata = base_metadata

                # Build vector with sparse embedding if available
                vector = {
                    "id": vector_id,
                    "values": dense_embedding,
                    "metadata": cleaned_metadata
                }
                
                # Add sparse embedding for hybrid search if available
                sparse_embedding = embedding_data.get("sparse_embedding")
                if sparse_embedding and sparse_embedding.get("indices"):
                    vector["sparse_values"] = sparse_embedding

                vectors_to_upsert.append(vector)

            logger.debug(f"Prepared {len(vectors_to_upsert)} vectors for upsert")
            
            # Index to Pinecone in batches
            total_indexed = 0
            for i in range(0, len(vectors_to_upsert), batch_size):
                batch = vectors_to_upsert[i:i + batch_size]
                logger.debug(f"Processing batch {i//batch_size + 1} with {len(batch)} vectors")

                upsert_params = {
                    "vectors": batch
                }

                if namespace and self.config.use_namespaces:
                    upsert_params["namespace"] = namespace
                    logger.debug(f"Upserting to namespace: {namespace}")
                else:
                    logger.debug("Upserting to default namespace")

                # Production Fix #4: Retry logic for transient Pinecone errors
                max_retries = 3
                retry_delay = 1.0  # Initial delay in seconds
                
                for attempt in range(max_retries):
                    try:
                        result = self.pinecone_index.upsert(**upsert_params)
                        logger.debug(f"Upsert result: {result}")
                        total_indexed += len(batch)
                        break  # Success - exit retry loop
                    except Exception as e:
                        error_str = str(e).lower()
                        is_transient = any(x in error_str for x in ['429', '503', 'rate limit', 'timeout', 'connection'])
                        
                        if is_transient and attempt < max_retries - 1:
                            logger.warning(f"Transient Pinecone error (attempt {attempt + 1}/{max_retries}): {e}")
                            await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                            continue
                        elif 'metadata size' in error_str:
                            # Metadata too large - log and skip this batch
                            logger.error(f"Metadata size error (skipping batch): {e}")
                            logger.warning(f"Skipped {len(batch)} vectors due to metadata size limit")
                            break  # Don't retry on metadata size errors
                        else:
                            logger.error(f"Error upserting batch: {e}")
                            logger.debug(f"Failed batch vector IDs: {[v['id'] for v in batch]}")
                            raise

                logger.info(f"Indexed batch of {len(batch)} vectors to Pinecone")

                # Small delay between batches
                if i + batch_size < len(vectors_to_upsert):
                    await asyncio.sleep(0.1)

            logger.info(f"Successfully indexed {total_indexed} vectors to Pinecone")
            return total_indexed
            
        except Exception as e:
            logger.error(f"Error indexing documents with Gemini: {e}")
            return 0
    
    def _generate_sparse_embedding(self, text: str) -> Dict[str, List]:
        """Generate sparse embedding using Pinecone Text BM25Encoder."""
        if not self.bm25_encoder:
            return {"indices": [], "values": []}

        try:
            # Add text to corpus
            self.corpus.append(text)

            # Only fit BM25 once when we have enough documents
            # This fixes the performance bug of refitting on every document
            if not self._bm25_fitted:
                min_docs = int(os.getenv("BM25_MIN_DOCS", "5"))
                if len(self.corpus) >= min_docs:
                    self.bm25_encoder.fit(self.corpus)
                    self._bm25_fitted = True
                    logger.info(f"BM25 encoder fitted with {len(self.corpus)} documents")
                else:
                    # Not enough documents yet, return empty sparse vector
                    return {"indices": [], "values": []}

            # Generate sparse embedding
            sparse_embedding = self.bm25_encoder.encode_queries([text])
            return {
                "indices": sparse_embedding[0]["indices"],
                "values": sparse_embedding[0]["values"]
            }

        except Exception as e:
            logger.error(f"Error generating sparse embedding: {e}")
            return {"indices": [], "values": []}
    
    def _generate_sparse_embedding_for_text(self, text: str) -> Dict[str, List]:
        """Generate sparse embedding for a single text.
        
        This method assumes BM25 encoder is already fitted (call after fitting on corpus).
        Used by generate_embeddings() after fitting BM25 on all documents.
        """
        if not self.bm25_encoder or not self._bm25_fitted:
            return {"indices": [], "values": []}

        try:
            # Use encode_documents for indexing (vs encode_queries for searching)
            sparse_embedding = self.bm25_encoder.encode_documents([text])
            if sparse_embedding and len(sparse_embedding) > 0:
                return {
                    "indices": sparse_embedding[0].get("indices", []),
                    "values": sparse_embedding[0].get("values", [])
                }
            return {"indices": [], "values": []}

        except Exception as e:
            logger.error(f"Error generating sparse embedding for text: {e}")
            return {"indices": [], "values": []}
    
    async def query_similar_documents(self, query: str, top_k: int = 10, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query for similar documents using Gemini embeddings."""
        try:
            if not self.pinecone_index:
                logger.error("Pinecone index not available")
                return []
            
            # Get query embedding from Gemini
            query_embeddings = await self._get_gemini_embeddings([query])
            if not query_embeddings:
                return []
            
            query_vector = query_embeddings[0]
            
            # Prepare query parameters
            query_params = {
                "vector": query_vector,
                "top_k": top_k,
                "include_metadata": True
            }
            
            if namespace and self.config.use_namespaces:
                query_params["namespace"] = namespace
            
            results = self.pinecone_index.query(**query_params)
            
            return results.matches if results.matches else []
            
        except Exception as e:
            logger.error(f"Error querying Pinecone with Gemini: {e}")
            return []
