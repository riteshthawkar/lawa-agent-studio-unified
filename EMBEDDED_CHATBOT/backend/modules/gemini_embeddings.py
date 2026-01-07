"""
Gemini Embeddings module for the embedded chatbot backend.
Uses Gemini's embedding API to generate dense embeddings that match the indexing backend.
"""

import asyncio
import os
import logging
from typing import List, Optional
import httpx
try:
    from langchain.embeddings.base import Embeddings
except ImportError:
    from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)

# Gemini API configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_EMBEDDING_DIMENSIONS = int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "1024"))
GEMINI_EMBEDDING_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"


class GeminiEmbeddings(Embeddings):
    """
    Gemini embeddings class that provides an interface compatible with LangChain embeddings.
    This allows drop-in replacement of HuggingFaceEmbeddings.
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        model_name: str = GEMINI_EMBEDDING_MODEL,
        dimensions: int = GEMINI_EMBEDDING_DIMENSIONS
    ):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name
        self.dimensions = dimensions
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required for Gemini embeddings")
        
        logger.info(f"Initialized GeminiEmbeddings with model={model_name}, dimensions={dimensions}")
    
    async def _embed_single_async(self, text: str) -> List[float]:
        """Generate embedding for a single text using Gemini API."""
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": f"models/{self.model_name}",
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": self.dimensions
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        GEMINI_EMBEDDING_URL,
                        headers=headers,
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if "embedding" in result and "values" in result["embedding"]:
                            return result["embedding"]["values"]
                        else:
                            logger.error(f"Unexpected Gemini response structure: {result}")
                            return []
                    elif response.status_code in [429, 500, 503]:
                        # Retryable errors
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            logger.warning(f"Gemini API error {response.status_code}, retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Gemini API failed after {max_retries} retries: {response.text}")
                            return []
                    else:
                        logger.error(f"Gemini API error {response.status_code}: {response.text}")
                        return []
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Gemini embedding error: {e}, retrying...")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Gemini embedding failed after retries: {e}")
                    return []
        
        return []
    
    def embed_query(self, text: str) -> List[float]:
        """
        Synchronous method to embed a single query.
        Required for LangChain compatibility.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in an async context, create a new task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._embed_single_async(text))
                    return future.result()
            else:
                return loop.run_until_complete(self._embed_single_async(text))
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self._embed_single_async(text))
    
    async def aembed_query(self, text: str) -> List[float]:
        """Async method to embed a single query."""
        return await self._embed_single_async(text)
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Synchronous method to embed multiple documents.
        Required for LangChain compatibility.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._embed_documents_async(texts))
                    return future.result()
            else:
                return loop.run_until_complete(self._embed_documents_async(texts))
        except RuntimeError:
            return asyncio.run(self._embed_documents_async(texts))
    
    async def _embed_documents_async(self, texts: List[str]) -> List[List[float]]:
        """Async method to embed multiple documents."""
        # Process in parallel with batching to avoid rate limits
        embeddings = []
        batch_size = 5  # Process 5 at a time
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_results = await asyncio.gather(
                *[self._embed_single_async(text) for text in batch],
                return_exceptions=True
            )
            
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"Embedding failed: {result}")
                    embeddings.append([0.0] * self.dimensions)  # Fallback
                elif isinstance(result, list):
                    embeddings.append(result)
                else:
                    embeddings.append([0.0] * self.dimensions)
            
            # Small delay between batches to avoid rate limiting
            if i + batch_size < len(texts):
                await asyncio.sleep(0.1)
        
        return embeddings


def initialize_gemini_embeddings() -> GeminiEmbeddings:
    """Initialize and return the Gemini embedding model."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is required")
    
    return GeminiEmbeddings(
        api_key=api_key,
        dimensions=GEMINI_EMBEDDING_DIMENSIONS
    )
