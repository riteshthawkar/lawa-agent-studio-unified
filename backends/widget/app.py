import asyncio
import re
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# Import modules
from modules.config import logger, validate_env_vars, get_system_prompt, RAG_APP_NAME, OPENAI_TIMEOUT, INTEGRATION_MODE, LAWA_PINECONE_INDEX_NAME
from modules.schemas import ChatRequest
from modules.utils import safe_send, format_query
from modules.citations import process_citations
from modules.retrieval import initialize_retrieval_components, rerank_docs, fetch_balanced_documents
from pinecone import Pinecone
from modules.query_rewriting import query_rewriting_agent, openai_client

# LAWA Platform Integration
from modules.lawa_integration import initialize_lawa_integration, close_lawa_integration, lawa_integration

# Geo-location service
from modules.geo_location import lookup_ip, get_client_ip_from_websocket

# Import database modules - UPDATED for Django Integration
from modules.database.django_repository import DjangoChatRepository

# Import health check endpoints
from health_endpoints import router as health_router

# ------------------------------------------------------------------------------
# Initialize application and validate environment
# ------------------------------------------------------------------------------
validate_env_vars()

# ------------------------------------------------------------------------------
# Lifespan manager for database connection pool
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize all components
    logger.info("Application startup: Initializing components...")
    
    # --- LAWA Platform Database Integration (Single Source of Truth) ---
    await initialize_lawa_integration()
    
    # Expose the pool to app.state for convenience
    if lawa_integration.pool:
        app.state.pool = lawa_integration.pool
        logger.info("LAWA Django database pool initialized and assigned to app.state.")
    else:
        logger.warning("LAWA integration failed to initialize database pool. Chat saving will be disabled.")
        app.state.pool = None

    # --- Retrieval Components (Embeddings, BM25) ---
    app.state.embed_model, app.state.bm25_encoder = initialize_retrieval_components()
    logger.info("Embedding model and BM25 encoder initialized and assigned to app.state.")

    # --- Pinecone Client and Async Indexes ---
    pinecone_api_key = os.getenv("PINECONE_API_KEY")
    pc = Pinecone(api_key=pinecone_api_key)
    
    if INTEGRATION_MODE == "lawa":
        # LAWA Platform Integration - Single unified index
        lawa_index_name = LAWA_PINECONE_INDEX_NAME
        logger.info(f"LAWA Integration Mode: Connecting to unified index '{lawa_index_name}'...")
        app.state.pinecone_lawa_index = pc.Index(lawa_index_name)
        # Maintain compatibility with existing code by setting both to the same index
        app.state.pinecone_summary_index = app.state.pinecone_lawa_index
        app.state.pinecone_text_index = app.state.pinecone_lawa_index
        logger.info("LAWA unified Pinecone index connected and assigned to app.state.")
    else:
        # Legacy MBZUAI Configuration - Separate indexes
        summary_index_name = os.getenv("PINECONE_SUMMARY_INDEX_NAME", "mbzuai-summary-only-index-latest")
        text_index_name = os.getenv("PINECONE_TEXT_INDEX_NAME", "mbzuai-text-only-index-latest")
        logger.info(f"Legacy Mode: Connecting to separate indexes '{summary_index_name}' and '{text_index_name}'...")
        app.state.pinecone_summary_index = pc.Index(summary_index_name)
        app.state.pinecone_text_index = pc.Index(text_index_name)
        logger.info("Legacy Pinecone indexes connected and assigned to app.state.")
    
    yield # Application runs here

    # Shutdown: Disconnect from all services
    logger.info("Application shutdown: Cleaning up resources...")
    
    # Close LAWA integration
    await close_lawa_integration()
    logger.info("LAWA integration closed.")

# ------------------------------------------------------------------------------
# Initialize FastAPI app with CORS middleware and lifespan manager
# ------------------------------------------------------------------------------
app = FastAPI(lifespan=lifespan)

# CORS configuration (allow all origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Exception Handlers
# ------------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Custom handler for HTTP exceptions to silence noisy 404 logs from bot probing.
    """
    if exc.status_code == 404:
        # Just return 404 without logging to error log/console
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# Add health check routes
app.include_router(health_router)

# ------------------------------------------------------------------------------
# REST endpoint for testing chatbots (Admin Dashboard)
# This endpoint processes messages but does NOT save to database
# ------------------------------------------------------------------------------

from pydantic import BaseModel
from typing import Optional, List

class TestChatRequest(BaseModel):
    """Request model for test chat endpoint"""
    message: str
    language: str = "en"
    previous_chats: List[dict] = []

class TestChatResponse(BaseModel):
    """Response model for test chat endpoint"""
    response: str
    sources: List[dict] = []
    is_test: bool = True

@app.get("/chat/test/{api_key}")
async def test_chat_page(request: Request, api_key: str):
    """
    Test page for chatbot - renders a simple chat interface.
    This is for testing from the admin dashboard without saving data.
    """
    # Simply render the test template
    # Validation happens when connecting to WebSocket
    return templates.TemplateResponse("test_chat.html", {"request": request, "api_key": api_key})

@app.get("/v1/chatbot/{api_key}/starters/")
async def get_chatbot_starters(api_key: str):
    """
    Get conversation starters for a chatbot.
    Used by the widget frontend.
    """
    starters = await lawa_integration.get_chatbot_starters(api_key)
    if starters is None:
        raise HTTPException(status_code=404, detail="Chatbot not found or invalid API key")
    
    return {"starters": starters}

@app.post("/chat/test/{api_key}", response_model=TestChatResponse)
async def test_chat_endpoint(api_key: str, request: TestChatRequest):
    """
    Test chat endpoint for admin dashboard.
    
    This endpoint:
    - Validates the API key
    - Processes the message through the RAG pipeline
    - Returns the response WITHOUT saving to database
    - Does NOT count towards analytics
    
    This allows admins to test their chatbot without polluting analytics data.
    """
    # Validate API key and get site information
    site_info = None
    if INTEGRATION_MODE == "lawa":
        site_info = await lawa_integration.validate_api_key(api_key)
        if not site_info:
            logger.warning(f"Invalid API key for test endpoint: {api_key[:10]}...")
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid API key", "response": "", "sources": [], "is_test": True}
            )
        logger.info(f"Test chat request for site: {site_info['site_domain']}")
    else:
        return JSONResponse(
            status_code=400,
            content={"error": "Test endpoint only available in LAWA mode", "response": "", "sources": [], "is_test": True}
        )
    
    question = request.message
    language = request.language
    previous_chats = request.previous_chats
    
    try:
        # Apply query rewriting agent with categories for classification
        query_categories = site_info.get('query_categories', []) if site_info else []
        chatbot_config = site_info.get('chatbot_config', {}) if site_info else {}
        
        agent_result = await query_rewriting_agent(
            question, language, previous_chats,
            site_domain=site_info['site_domain'],
            organization_name=site_info['site_domain'],
            query_categories=query_categories,
            description=site_info.get('description'),
            special_instructions=chatbot_config.get('special_instructions'),
            chatbot_name=site_info.get('chatbot_name')
        )
        
        # Handle direct responses
        if agent_result["action"] in ["respond", "identity"]:
            response = agent_result["response"]
            if agent_result["action"] == "identity" and site_info:
                response = f"I am an AI assistant for {site_info['site_domain']}."
            
            return TestChatResponse(response=response, sources=[], is_test=True)
        
        # RAG Pipeline - fetch documents
        rewritten_queries = agent_result.get("rewritten_queries", {})
        
        docs = []
        namespace = site_info['namespace'] if site_info else None
        docs = await fetch_balanced_documents(
            rewritten_queries=rewritten_queries,
            pinecone_summary_index=app.state.pinecone_summary_index,
            pinecone_text_index=app.state.pinecone_text_index,
            embed_model=app.state.embed_model,
            bm25_encoder=app.state.bm25_encoder,
            namespace=namespace
        )
        
        if not docs:
            no_docs_msg = f"I don't have specific information about that topic for {site_info['site_domain'] if site_info else 'this site'}."
            return TestChatResponse(response=no_docs_msg, sources=[], is_test=True)
        
        # Rerank
        try:
            final_docs = await rerank_docs(agent_result.get("final_query", question), docs)
            if not final_docs:
                final_docs = docs[:5]
        except Exception:
            final_docs = docs[:5]
        
        # Generate response
        formatted_query = format_query(agent_result.get("final_query", question), language, final_docs)
        # Setup system prompt with context
        chatbot_config = site_info.get('chatbot_config', {}) if site_info else {}
        system_prompt = get_system_prompt(
            site_domain=site_info['site_domain'] if site_info else None,
            organization_name=site_info.get('site_name') if site_info else None,
            special_instructions=chatbot_config.get('special_instructions'),
            chatbot_tone=chatbot_config.get('chatbot_tone'),
            response_length=chatbot_config.get('response_length'),
            description=site_info.get('description'),
            chatbot_name=site_info.get('chatbot_name')
        )
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": formatted_query}
            ],
            timeout=OPENAI_TIMEOUT
        )
        
        raw_answer = response.choices[0].message.content
        updated_answer, citations = process_citations(raw_answer, final_docs)
        
        # Return response WITHOUT saving to database
        return TestChatResponse(
            response=updated_answer,
            sources=citations,
            is_test=True
        )
        
    except Exception as e:
        logger.exception(f"Error in test chat endpoint: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "response": "I encountered an error while generating a response.", "sources": [], "is_test": True}
        )

# ------------------------------------------------------------------------------
# WebSocket endpoint for chat functionality
# ------------------------------------------------------------------------------

@app.websocket("/chat/{api_key}")
async def lawa_websocket_endpoint(websocket: WebSocket, api_key: str):
    """LAWA Platform WebSocket endpoint with API key validation for site-specific chatbots."""
    
    # Validate API key and get site information
    site_info = None
    if INTEGRATION_MODE == "lawa":
        site_info = await lawa_integration.validate_api_key(api_key)
        if not site_info:
            logger.warning(f"Invalid API key attempted connection: {api_key[:10]}...")
            await websocket.close(code=4001, reason="Invalid API key")
            return
        
        logger.info(f"LAWA client connected for site: {site_info['site_domain']} (namespace: {site_info['namespace']})")
    
    await websocket.accept()
    
    # Send connection confirmation with site info
    connection_message = {
        "status": "connected", 
        "message": "Connected to LAWA assistant.",
    }
    if site_info:
        connection_message["site_info"] = {
            "domain": site_info['site_domain'],
            "chatbot_name": site_info['chatbot_name'],
            "greeting_message": site_info.get('greeting_message', 'Hello! How can I help you today?'),
            "description": site_info.get('description', ''),
            "primary_color": site_info.get('primary_color', '#2563eb'),
            "text_color": site_info.get('text_color', '#ffffff'),
            "position": site_info.get('position', 'bottom-right'),
            "theme": site_info.get('theme', 'auto'),
            "placeholder_text": site_info.get('placeholder_text', 'Type your message...')
        }
    
    try:
        await safe_send(websocket, connection_message)
    except Exception:
        pass

    # Lazy session creation - only create when first message is sent
    # This prevents empty sessions from being stored
    session_id = None
    client_ip = None
    geo_data = None
    session_created = False  # Track if session has been created

    # Extract client IP for geo-location (do this early, before session creation)
    if site_info:
        client_ip = get_client_ip_from_websocket(websocket)
        if client_ip:
            geo_location = lookup_ip(client_ip)
            geo_data = geo_location.to_dict()
            logger.info(f"Geo-location for {client_ip}: {geo_data.get('country_code', 'unknown')}")

    async def ensure_session_created(device_type=None, referrer=None, provided_session_id=None):
        """Lazily create session on first message - prevents empty sessions"""
        nonlocal session_id, session_created

        if session_created or not site_info or not app.state.pool:
            return session_id

        # 1. If frontend provided a session ID, check if it exists in DB
        if provided_session_id:
             try:
                 exists = await DjangoChatRepository.get_session(app.state.pool, provided_session_id)
                 if exists:
                     session_id = provided_session_id
                     session_created = True
                     logger.info(f"Resumed existing session {session_id} for site {site_info['site_domain']}")
                     # Optionally update analytics for resumed session
                     # await DjangoChatRepository.update_session_analytics(app.state.pool, session_id, device_type, referrer)
                     return session_id
             except Exception as e:
                 logger.warning(f"Failed to check/resume session {provided_session_id}: {e}")

        # 2. If no valid session ID from frontend, create a new one
        # Check Quota BEFORE creating session
        org_id = site_info.get('org_id')
        daily_limit = site_info.get('daily_limit', 100) # Default to basic
        
        if org_id:
             reached, usage = await DjangoChatRepository.check_daily_conversation_limit(
                 app.state.pool, org_id, daily_limit
             )
             if reached:
                 logger.warning(f"Quota exceeded for org {org_id} (Limit: {daily_limit})")
                 raise ValueError("Quota Exceeded")

        session_data = {
            'connection_type': 'websocket',
            'api_key': api_key,
            'source': 'embedded_widget'
        }

        created_session_id = await DjangoChatRepository.create_session(
            app.state.pool,
            site_id=site_info['site_id'],
            chatbot_id=site_info['chatbot_id'],
            session_data=session_data,
            geo_country_code=geo_data.get('country_code') if geo_data else None,
            geo_country_name=geo_data.get('country_name') if geo_data else None,
            geo_region=geo_data.get('region') if geo_data else None,
            geo_city=geo_data.get('city') if geo_data else None,
            client_ip=client_ip,
            device_type=device_type,
            referrer=referrer
        )

        if created_session_id:
            session_id = created_session_id
            session_created = True
            logger.info(f"Created Django session {session_id} for site {site_info['site_domain']} (IP: {client_ip or 'unknown'})")
            
            # Track Usage Event (New Conversation)
            if org_id:
                try:
                    await DjangoChatRepository.track_usage_event(
                        app.state.pool,
                        org_id=org_id,
                        site_id=site_info['site_id'],
                        chatbot_id=site_info['chatbot_id'],
                        session_id=session_id
                    )
                except Exception as e:
                     logger.error(f"Failed to track usage event: {e}")

        else:
            logger.warning("Failed to create Django session, continuing without session tracking")

        return session_id

    # Main chat loop
    while True:
        try:
            # Wait for client messages
            data = await websocket.receive_json()
            await safe_send(websocket, {"status": "received", "message": "Request received. Preparing to process..."})
            
            # --- Feedback Handling (LAWA Mode) ---
            if "feedback" in data and "id" in data:
                try:
                    # 'id' from frontend corresponds to message_id in DB (UUID for Django)
                    message_id_raw = data.get("id") 
                    feedback_type = data.get("feedback")
                    comment = data.get("comment", "")
                    
                    if message_id_raw and feedback_type in ["like", "dislike"]:
                        logger.info(f"Received feedback '{feedback_type}' for message ID: {message_id_raw}")
                        
                        # Get client info
                        client_ip = websocket.client.host if hasattr(websocket, 'client') else None
                        user_agent = websocket.headers.get('user-agent', '')
                        
                        # Use Django repository for feedback
                        try:
                            # Django uses UUIDs for message IDs, not integers
                            message_id_str = str(message_id_raw)
                            
                            # 1. Update the message row
                            updated = await DjangoChatRepository.update_message_feedback(
                                app.state.pool, message_id_str, feedback_type
                            )
                            
                            # 2. Add detailed feedback entry
                            if updated:
                                await DjangoChatRepository.create_detailed_feedback(
                                    app.state.pool,
                                    message_id=message_id_str,
                                    feedback_type=feedback_type,
                                    # comment=comment, # Removed
                                    ip_address=client_ip,
                                    user_agent=user_agent
                                )
                                
                                await safe_send(websocket, {
                                    "status": "feedback_updated", 
                                    "id": message_id_raw,
                                    "feedback_type": feedback_type
                                })
                            else:
                                await safe_send(websocket, {
                                    "status": "feedback_failed", 
                                    "id": message_id_raw,
                                    "error": "Message not found"
                                })
                                
                        except Exception as uuid_err:
                             logger.error(f"Error processing message ID for feedback: {uuid_err}")
                             await safe_send(websocket, {"status": "feedback_error", "error": "Invalid ID format"})
                            
                    else:
                        logger.warning(f"Invalid feedback data: id={message_id_raw}, feedback={feedback_type}")
                        await safe_send(websocket, {"status": "invalid_feedback_data", "id": message_id_raw})
                
                except Exception as feedback_err:
                    logger.exception(f"Error processing feedback: {feedback_err}")
                    await safe_send(websocket, {"status": "feedback_error", "id": data.get('id', 'unknown')})
                
                continue
            
            # Chat message handling
            try:
                chat_request = ChatRequest(**data)
            except ValidationError as ve:
                error_details = str(ve)
                logger.exception(f"LAWA validation error: {error_details}")
                await safe_send(websocket, {
                    "response": f"Invalid request format. Required fields: question, language.", 
                    "error": "validation_error",
                    "error_details": error_details,
                    "sources": []
                })
                continue

            question = chat_request.question
            language = chat_request.language
            previous_chats = chat_request.previous_chats

            # Start timing for latency tracking
            request_start_time = time.time()

            # Extract analytics fields from request
            conversation_turn = chat_request.conversation_turn
            device_type = chat_request.device_type
            referrer = chat_request.referrer
            
            # Check if frontend provided a session ID to resume matches backend expectations
            provided_session_id = getattr(chat_request, 'session_id', None)

            # Lazy session creation - only create/resume session on first actual message
            # This prevents empty sessions from being stored in the database
            # device_type and referrer are passed during creation
            try:
                await ensure_session_created(device_type=device_type, referrer=referrer, provided_session_id=provided_session_id)
            except ValueError as ve:
                if str(ve) == "Quota Exceeded":
                    logger.warning(f"Blocking chat request due to quota limits for site {site_info.get('site_domain', 'unknown')}")
                    await safe_send(websocket, {
                        "response": "⚠️ Usage Limit Reached: This chatbot has exceeded its daily conversation limit. Please try again tomorrow.",
                        "sources": [],
                        "id": str(uuid.uuid4())
                    })
                    continue
                else:
                    raise ve
            # This allows us to store the query category with the user message

            # Apply query rewriting agent with categories for classification
            query_categories = site_info.get('query_categories', []) if site_info else []
            if site_info:
                chatbot_config = site_info.get('chatbot_config', {})
                agent_result = await query_rewriting_agent(
                    question, language, previous_chats,
                    site_domain=site_info['site_domain'],
                    organization_name=site_info['site_domain'],
                    query_categories=query_categories,
                    description=site_info.get('description'),
                    special_instructions=chatbot_config.get('special_instructions'),
                    chatbot_name=site_info.get('chatbot_name')
                )
            else:
                agent_result = await query_rewriting_agent(question, language, previous_chats)

            # Extract classification for analytics
            classification = agent_result.get('classification', {})
            query_category = classification.get('category')
            query_category_confidence = classification.get('confidence')

            # Save USER message to Django DB with classification and analytics
            if session_id and app.state.pool:
                try:
                    await DjangoChatRepository.save_chat_message(
                        app.state.pool,
                        session_id=session_id,
                        role="user",
                        content=question,
                        tokens_in=0,
                        tokens_out=0,
                        query_category=query_category,
                        query_category_confidence=query_category_confidence,
                        conversation_turn=conversation_turn
                    )
                except Exception as e:
                    logger.error(f"Failed to save user message: {e}")

            # Handle direct responses
            if agent_result["action"] in ["respond", "identity"]:
                response = agent_result["response"]
                if agent_result["action"] == "identity" and site_info:
                    response = f"I am an AI assistant for {site_info['site_domain']}."
                
                await safe_send(websocket, {
                    "response": response, 
                    "sources": [],
                    "id": str(uuid.uuid4())
                })
                
                # Save assistant direct response
                if session_id and app.state.pool:
                    latency_ms = int((time.time() - request_start_time) * 1000)
                    await DjangoChatRepository.save_chat_message(
                        app.state.pool,
                        session_id=session_id,
                        role="assistant",
                        content=response,
                        tokens_in=0,
                        tokens_out=len(response.split()),
                        latency_ms=latency_ms,
                        conversation_turn=conversation_turn
                    )
                continue

            # RAG Pipeline
            chat_trace_id = str(uuid.uuid4())
            rewritten_queries = agent_result.get("rewritten_queries", {})
            
            await safe_send(websocket, {"status": "retrieving", "message": "Searching relevant content...", "status_text": 0})
            
            docs = []
            try:
                namespace = site_info['namespace'] if site_info else None
                docs = await fetch_balanced_documents(
                    rewritten_queries=rewritten_queries,
                    pinecone_summary_index=websocket.app.state.pinecone_summary_index,
                    pinecone_text_index=websocket.app.state.pinecone_text_index,
                    embed_model=websocket.app.state.embed_model,
                    bm25_encoder=websocket.app.state.bm25_encoder,
                    namespace=namespace
                )
                
                if not docs:
                    no_docs_msg = f"I don't have specific information about that topic for {site_info['site_domain'] if site_info else 'this site'}."
                    await safe_send(websocket, {
                        "response": no_docs_msg,
                        "sources": [],
                        "id": chat_trace_id
                    })
                    if session_id and app.state.pool:
                        latency_ms = int((time.time() - request_start_time) * 1000)
                        await DjangoChatRepository.save_chat_message(
                            app.state.pool,
                            session_id=session_id,
                            role="assistant",
                            content=no_docs_msg,
                            latency_ms=latency_ms,
                            conversation_turn=conversation_turn
                        )
                    continue

            except Exception as e:
                logger.exception(f"Error fetching documents: {e}")
                err_msg = "I encountered an error while searching for information."
                await safe_send(websocket, {"response": err_msg, "sources": [], "id": chat_trace_id})
                continue

            # Rerank
            await safe_send(websocket, {"status": "reranking", "message": "Analyzing content...", "status_text": 1})
            try:
                final_docs = await rerank_docs(agent_result.get("final_query", question), docs)
                if not final_docs:
                     final_docs = docs[:5] # Fallback
            except Exception:
                final_docs = docs[:5]

            # Generate response
            await safe_send(websocket, {"status": "generating", "message": "Generating response...", "status_text": 2})

            try:
                formatted_query = format_query(agent_result.get("final_query", question), language, final_docs)

                # Extract chatbot configuration
                chatbot_config = site_info.get('chatbot_config', {}) if site_info else {}

                system_prompt = get_system_prompt(
                    site_domain=site_info['site_domain'] if site_info else None,
                    organization_name=site_info.get('site_name') if site_info else None,
                    special_instructions=chatbot_config.get('special_instructions'),
                    chatbot_tone=chatbot_config.get('chatbot_tone'),
                    response_length=chatbot_config.get('response_length')
                )

                # Use streaming for better UX - send chunks as they arrive
                stream = await openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": formatted_query}
                    ],
                    timeout=OPENAI_TIMEOUT,
                    stream=True  # Enable streaming
                )

                # Collect the full response while streaming chunks to the client
                raw_answer = ""
                await safe_send(websocket, {"status": "streaming", "message": "Streaming response...", "status_text": 2})

                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        raw_answer += content
                        # Send each chunk to the client for real-time display
                        await safe_send(websocket, {
                            "response": content,
                            "status": "streaming"
                        })

                # Process citations after streaming is complete
                updated_answer, citations = process_citations(raw_answer, final_docs)

                # We need the inserted message ID to return to the frontend for feedback
                saved_message_id = None

                # Save assistant response to Django DB
                if session_id and app.state.pool:
                    try:
                        # Estimate tokens
                        tokens_in = len(formatted_query.split()) # Very rough
                        tokens_out = len(raw_answer.split())
                        latency_ms = int((time.time() - request_start_time) * 1000)

                        saved_message_id = await DjangoChatRepository.save_chat_message(
                            app.state.pool,
                            session_id=session_id,
                            role="assistant",
                            content=updated_answer,
                            citations=citations,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            latency_ms=latency_ms,
                            conversation_turn=conversation_turn
                        )
                    except Exception as e:
                        logger.error(f"Error saving assistant response: {e}")

                # Send final response with sources and message ID for feedback
                await safe_send(websocket, {
                    "response": updated_answer,
                    "sources": citations,
                    "id": str(saved_message_id) if saved_message_id else chat_trace_id,
                    "done": True  # Signal that streaming is complete
                })

            except Exception as e:
                logger.exception(f"Error generating response: {e}")
                await safe_send(websocket, {
                    "response": "I encountered an error while generating a response.",
                    "sources": [],
                    "id": chat_trace_id
                })

        except WebSocketDisconnect:
            logger.info(f"Client disconnected")
            break
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            break