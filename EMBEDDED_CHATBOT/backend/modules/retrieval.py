import asyncio
import os
import json
from typing import List, Dict, Any, Optional, Union
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document
from pinecone_text.sparse import BM25Encoder
from langchain_community.retrievers.pinecone_hybrid_search import PineconeHybridSearchRetriever
from pydantic import BaseModel
import httpx
from datetime import datetime
from openai import AsyncOpenAI

from modules.config import (
    logger,
    RETRIEVAL_K,
    RERANKER_TOP_N,
    TOTAL_DOCS_TO_RERANK,
    OPENAI_TIMEOUT,
    BM25_FILE_PATH,
    MAX_RETRIES,
    RETRY_DELAY,
    HYBRID_ALPHA,
)
from modules.gemini_embeddings import GeminiEmbeddings, initialize_gemini_embeddings

# --- OpenAI Client Initialization ---
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.error("OPENAI_API_KEY not found in environment variables.")
client = AsyncOpenAI(api_key=api_key)

# --- Pydantic Models for Type Hinting and Validation ---
class Document_reference(BaseModel):
    index: int
    source_url: str

class Ranked_Documents(BaseModel):
    ranked_documents: List[Document_reference]

# --- Constants ---
BM25_FILE = BM25_FILE_PATH

# --- Reranker System Prompt ---
def get_reranker_system_prompt(is_time_sensitive: bool = False):
    current_date_str = datetime.now().strftime("%B %d, %Y")
    
    time_sensitive_rule = """
    4.  **Temporal Conflict Resolution (CRITICAL RULE)**:
        - If two or more documents present conflicting information (e.g., different admission deadlines, varying program details), you **MUST** prioritize the document with the most recent `document_date`.
        - If dates are unavailable, you must highlight that the information may be from different time periods and could be outdated.
    """ if is_time_sensitive else """
    4.  **Temporal Awareness & Recency**:
        - Use the `document_date` from the metadata when available. Prefer documents with recent dates for time-sensitive topics.
    """

    return f"""
As an AI assistant, your task is to re-rank a list of retrieved documents based on their **strict relevance, reliability, and metadata alignment** to a user's query.

**Today's Date**: {current_date_str}

--- 

### Core Re-ranking Principle: Content-First Relevance

Your primary goal is to use the document's `DOCUMENT_TITLE` and `DOCUMENT_CONTENT` as the **strongest signals of relevance**. Evaluate how well each document answers the user's query.

### Hallucination Policy (Strict)

- Do NOT add or infer content not present in the provided document metadata or content snippets.
- If relevance is unclear, exclude the document rather than guessing.
- Output must be valid JSON only.

### Re-ranking Rules

    1.  **Content Alignment (Highest Priority)**:
        - A document is highly relevant if its `DOCUMENT_TITLE` and `DOCUMENT_CONTENT` directly address the user's query.
        - Prioritize documents that provide specific, detailed answers.

    2.  **Scope Limitation**:
        - ONLY retain documents strictly related to the organization or topic at hand.

    3.  **Source Authority Priority**:
        - Prioritize official sources and documentation.
        - Deprioritize external news articles, blogs, or third-party websites unless they are the only relevant sources

{time_sensitive_rule}

    5.  **Result Set Size (Soft Cap)**:
        - Limit the ranked list to a **maximum of {RERANKER_TOP_N} highly relevant documents**.

---

### Input Structure

You will be provided with:
- A **user query**.
- A list of documents, each containing:
    - `ORIGINAL_INDEX`: Numeric index.
    - `DOCUMENT_SOURCE`: URL or source path.
    - `DOCUMENT_TITLE`: The title of the document.
    - `DOCUMENT_CONTENT`: The text content.

Example input document format:
========
**ORIGINAL_INDEX:** 0
**DOCUMENT_SOURCE:** https://example.com/about
**DOCUMENT_TITLE:** About Us - Company Overview
**DOCUMENT_CONTENT:**
We are a leading technology company focused on innovation...
========

### Output Format

Your output **MUST** be a single, valid JSON object containing a single key, `ranked_documents`. The value should be a list of objects, where each object has two keys: `index` (the original index of the document) and `source_url` (the document's source URL).

- **DO NOT** include any documents that are not strictly relevant.
- **DO NOT** add any explanatory text, comments, or markdown formatting before or after the JSON object.

Example Output:
```json
{{
    "ranked_documents": [
        {{"index": 0, "source_url": "https://example.com/about"}},
        {{"index": 3, "source_url": "https://example.com/services"}}
    ]
}}
```
"""

# --- Reranking Function ---
async def openai_rerank_and_filter_docs(query: str, original_docs: List[Dict[str, Any]], is_time_sensitive: bool = False) -> List[Dict[str, Any]]:
    """
    Reranks and filters documents using OpenAI's gpt-4o-mini model.
    """
    if not original_docs:
        return []

    formatted_docs_str = format_docs_for_llm_prompt(original_docs)
    system_prompt = get_reranker_system_prompt(is_time_sensitive=is_time_sensitive)
    user_prompt = f"User Query: \"{query}\"\n\nDocuments:\n{formatted_docs_str}"

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=OPENAI_TIMEOUT,
            )
            content = response.choices[0].message.content
            parsed_json = json.loads(content)
            
            ranked_data = Ranked_Documents.model_validate(parsed_json)

            # Preserve the order returned by the reranker and guard index bounds
            ordered_docs: List[Dict[str, Any]] = []
            for ref in ranked_data.ranked_documents:
                idx = ref.index
                if isinstance(idx, int) and 0 <= idx < len(original_docs):
                    ordered_docs.append(original_docs[idx])
            return ordered_docs if ordered_docs else original_docs

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt == MAX_RETRIES - 1:
                logger.error("Max retries reached. Reranking failed.")
                return original_docs
            await asyncio.sleep(RETRY_DELAY)
    return original_docs

async def rerank_docs(query: str, docs: List[Dict[str, Any]], is_time_sensitive: bool = False) -> List[Dict[str, Any]]:
    """
    Selects, transforms, and reranks documents using a metadata-aware LLM reranker.
    """
    if not docs:
        return []

    docs_to_rerank = docs[:TOTAL_DOCS_TO_RERANK]
    logger.info(f"Sending {len(docs_to_rerank)} documents to be reranked.")

    reranked_docs = await openai_rerank_and_filter_docs(query, docs_to_rerank, is_time_sensitive=is_time_sensitive)
    return reranked_docs

async def fetch_balanced_documents(
    rewritten_queries: Dict[str, str],
    pinecone_summary_index: Any, # pinecone.Index
    pinecone_text_index: Any, # pinecone.Index
    embed_model: Union[GeminiEmbeddings, Any],  # GeminiEmbeddings or compatible
    bm25_encoder: BM25Encoder,
    namespace: Optional[str] = None,  # LAWA: Namespace for site-specific queries
    num_summary_docs: int = RETRIEVAL_K,
    num_text_docs: int = RETRIEVAL_K
) -> List[Document]:
    """
    Retrieves documents from both summary and text indexes in Pinecone using hybrid search,
    combining dense vectors and sparse BM25 vectors for improved retrieval.
    Uses specifically tailored queries for each index.
    Deduplicates and returns the combined results.
    """
    try:
        # Extract specialized queries for each index
        metadata_query = rewritten_queries.get("metadata_query", "")
        natural_language_query = rewritten_queries.get("natural_language_query", "")

        async def query_hybrid_retriever(index, query, k):
            query_info = f"{query[:50]}..." if len(query) > 50 else query
            namespace_info = f" in namespace '{namespace}'" if namespace else ""
            
            try:
                # Use standard Dense Retriever if Alpha is 1.0
                if HYBRID_ALPHA == 1.0:
                    logger.info(f"Using Dense-only retrieval (Alpha=1.0) for query: {query_info}{namespace_info}")
                    vectorstore = PineconeVectorStore(
                        index=index, 
                        embedding=embed_model,
                        text_key="original_content",
                        namespace=namespace
                    )
                    # Use standard retriever interface
                    retriever = vectorstore.as_retriever(search_kwargs={"k": k})
                    results = await retriever.ainvoke(query)
                    logger.info(f"Dense search retrieved {len(results)} documents{namespace_info}")
                    return results

                # Create PineconeHybridSearchRetriever with both dense and sparse encoders
                retriever_config = {
                    "embeddings": embed_model,
                    "sparse_encoder": bm25_encoder,
                    "index": index,
                    "alpha": HYBRID_ALPHA,  # Balance between dense and sparse (0.5 = equal weight)
                    "top_k": k,  # Number of results to return
                    "text_key": "original_content"  # Read from original_content field where full text is stored
                }
                
                # Add namespace if specified (LAWA integration)
                if namespace:
                    retriever_config["namespace"] = namespace
                    logger.info(f"Using namespace: {namespace} for hybrid search")
                
                hybrid_retriever = PineconeHybridSearchRetriever(**retriever_config)

                # Use the retriever to perform hybrid search
                logger.info(f"Performing hybrid search with query: {query_info}{namespace_info}")
                
                results = await asyncio.to_thread(
                    hybrid_retriever.invoke,
                    query
                )

                logger.info(f"Hybrid search retrieved {len(results)} documents{namespace_info}")
                return results
            except Exception as e:
                logger.exception(f"Error in hybrid search{namespace_info}: {e}")
                raise

        # Perform hybrid search on both indexes concurrently
        summary_task = query_hybrid_retriever(pinecone_summary_index, metadata_query, num_summary_docs)
        text_task = query_hybrid_retriever(pinecone_text_index, natural_language_query, num_text_docs)

        results = await asyncio.gather(summary_task, text_task, return_exceptions=True)

        all_docs = []
        if isinstance(results[0], list):
            logger.info(f"Retrieved {len(results[0])} documents from summary index using hybrid search.")
            all_docs.extend(results[0])
        else:
            logger.error(f"Error querying summary index with hybrid search: {results[0]}")

        if isinstance(results[1], list):
            logger.info(f"Retrieved {len(results[1])} documents from text index using hybrid search.")
            all_docs.extend(results[1])
        else:
            logger.error(f"Error querying text index with hybrid search: {results[1]}")

        unique_docs = {}
        skipped_count = 0
        for doc in all_docs:
            # Use page_id as the primary deduplication key
            page_id = doc.metadata.get('page_id')

            
            if not page_id:
                # Fallback to page_source + chunk_id if page_id is not available
                page_id = f"{doc.metadata.get('page_source', '')}_{doc.metadata.get('chunk_id', '')}"
            
            if page_id not in unique_docs:
                unique_docs[page_id] = doc
            else:
                skipped_count += 1
        
        final_docs = list(unique_docs.values())
        logger.info(f"Deduplication: Started with {len(all_docs)} total documents")
        logger.info(f"Deduplication: Skipped {skipped_count} duplicate documents")
        logger.info(f"Returning {len(final_docs)} unique documents after deduplication.")
        return final_docs

    except Exception as e:
        logger.exception("An error occurred during balanced document fetching.")
        # Propagate the exception to be handled by the caller
        raise

def format_docs_for_llm_prompt(docs: List[Dict[str, Any]]) -> str:
    """
    Formats a list of documents into a string suitable for an LLM prompt.
    Uses actual field names from the Pinecone index:
    - 'title' for document title
    - 'page_source' or 'url' for document source URL
    - 'page_content' for content (via LangChain's text_key)
    """
    formatted_docs = []
    for i, doc in enumerate(docs):
        # page_content is populated by LangChain from text_key (now set to original_content)
        # Fallback to metadata fields if page_content is empty
        if isinstance(doc, Document):
            page_content = doc.page_content if doc.page_content else doc.metadata.get('original_content', '')
            metadata = doc.metadata
        else:
            page_content = doc.get('page_content', doc.get('original_content', ''))
            metadata = doc.get('metadata', {})

        # Use actual field names from Pinecone metadata
        title = metadata.get("title", "No Title Available")
        # Try page_source first, then url, then fallback
        source = metadata.get("page_source", metadata.get("url", metadata.get("source", "N/A")))
        
        # Use chunk information if available
        chunk_info = ""
        chunk_index = metadata.get("chunk_index")
        total_chunks = metadata.get("total_chunks")
        if chunk_index is not None and total_chunks is not None and total_chunks > 1:
            chunk_info = f" (Part {int(chunk_index) + 1} of {int(total_chunks)})"

        doc_str = (
            f"========\n"
            f"**ORIGINAL_INDEX:** {i}\n"
            f"**DOCUMENT_SOURCE:** {source}\n"
            f"**DOCUMENT_TITLE:** {title}{chunk_info}\n"
            f"**DOCUMENT_CONTENT:**\n{page_content}\n"
            f"========"
        )
        formatted_docs.append(doc_str)
    
    return "\n".join(formatted_docs) 

def initialize_retrieval_components():
    """Initializes and returns the Gemini embedding model and BM25 encoder."""
    logger.info("Initializing retrieval components with Gemini embeddings...")
    try:
        embed_model = initialize_gemini_embeddings()
        # Use BM25Encoder.default() to match indexing backend - no file sharing needed
        bm25_encoder = BM25Encoder.default()
        logger.info("Retrieval components initialized: Gemini embeddings + Default BM25 Encoder")
        return embed_model, bm25_encoder
    except Exception as e:
        logger.exception("Failed to initialize retrieval components.")
        raise


# Tavily fallback removed: prefer explicit user-facing failure messaging in application layer.