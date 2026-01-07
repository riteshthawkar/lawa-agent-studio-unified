import logging
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from typing import List, Dict

from modules.config import logger

async def safe_send(websocket: WebSocket, message: dict):
    """Send messages safely over the websocket with proper error handling"""
    try:
        await websocket.send_json(message)
    except WebSocketDisconnect:
        logger.info("Client disconnected during send")
        raise
    except Exception as e:
        logger.exception("Error sending message:")
        raise

def format_docs(docs: List) -> str:
    """Format documents for inclusion in prompt. Works with LangChain Document objects.
    
    Uses field names from the Pinecone index:
    - 'page_source' or 'url' for the URL
    - 'title' for the page title
    - 'page_content' for the content (via LangChain text_key)
    """
    context = ""
    for index, doc in enumerate(docs):
        # Get metadata
        if hasattr(doc, 'metadata'):
            metadata = doc.metadata
            # Try page_source first, then url, then fallback
            source = metadata.get('page_source', metadata.get('url', metadata.get('source', 'N/A')))
            title = metadata.get('title', '')
        else:
            source = 'N/A'
            title = ''
        
        context += f"\n{'=' * 75}\n"
        context += f"**DOCUMENT CITATION INDEX:** {index + 1}\n"
        context += f"**DOCUMENT SOURCE:** {source}\n"
        if title:
            context += f"**DOCUMENT TITLE:** {title}\n"
        context += "\n"
        
        # Get content - prioritize page_content (populated by text_key), then original_content from metadata
        # LangChain populates page_content from the text_key field (now set to original_content)
        content = ""
        if hasattr(doc, 'page_content') and doc.page_content:
            content = doc.page_content
        elif hasattr(doc, 'metadata'):
            # Fallback: try to get from metadata fields
            content = doc.metadata.get('original_content', doc.metadata.get('page_content', ''))
        else:
            # Fallback for dict-like objects
            content = doc.get('original_content', doc.get('page_content', 'N/A'))
            
        context += f"**CONTENT:**\n{content}\n"
    
    if context: 
        context += f"{'=' * 75}\n"

    return context

def format_query(query: str, language: str, docs: List[dict]) -> str:
    """Format the query with language and document context"""
    formatted_docs = format_docs(docs)
    return f"**USER QUERY:** {query}\n**LANGUAGE:** {language}\n**CONTEXT:**\n{formatted_docs}" 