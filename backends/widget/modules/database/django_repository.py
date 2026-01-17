"""
Repository for Django database operations using asyncpg.
Matches the schema defined in backend/apps/chat/models.py
"""
import asyncpg
import json
from typing import List, Optional, Dict, Any
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

class DjangoChatRepository:
    """Repository for chat operations targeting the Django database schema."""
    
    @staticmethod
    async def create_session(
        pool: asyncpg.Pool,
        site_id: str,
        chatbot_id: str,
        session_data: Dict[str, Any] = None,
        user_id: Optional[str] = None,
        geo_country_code: Optional[str] = None,
        geo_country_name: Optional[str] = None,
        geo_region: Optional[str] = None,
        geo_city: Optional[str] = None,
        client_ip: Optional[str] = None,
        device_type: Optional[str] = None,
        referrer: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a new chat session in the chat_sessions table.
        Includes geo-location and analytics fields.
        """
        if not pool:
            logger.error("Database pool instance was not provided to create_session.")
            return None

        try:
            query = """
                INSERT INTO chat_sessions (
                    id, site_id, chatbot_id, user_id, session_data,
                    geo_country_code, geo_country_name, geo_region, geo_city, client_ip,
                    device_type, referrer,
                    started_at, last_activity, status, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), $1::uuid, $2::uuid, $3::uuid, $4::jsonb,
                    $5, $6, $7, $8, $9,
                    $10, $11,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                RETURNING id
            """

            async with pool.acquire() as conn:
                s_data = json.dumps(session_data if session_data else {})

                result = await conn.fetchrow(
                    query,
                    site_id,
                    chatbot_id,
                    user_id,
                    s_data,
                    geo_country_code,
                    geo_country_name,
                    geo_region,
                    geo_city,
                    client_ip,
                    device_type,
                    referrer
                )

                if result:
                    session_id = str(result['id'])
                    logger.info(f"Session created with ID: {session_id} (geo: {geo_country_code or 'unknown'}, device: {device_type or 'unknown'})")
                    return session_id
                return None

        except Exception as e:
            logger.error(f"Error creating session: {e}", exc_info=True)
            return None

    @staticmethod
    async def get_session(pool: asyncpg.Pool, session_id: str) -> bool:
        """
        Check if a session exists.
        """
        if not pool or not session_id:
            return False
            
        try:
            query = "SELECT 1 FROM chat_sessions WHERE id = $1::uuid"
            async with pool.acquire() as conn:
                result = await conn.fetchval(query, session_id)
                return bool(result)
        except Exception:
            # Handle invalid UUID format or DB errors gracefully
            return False

    @staticmethod
    async def save_chat_message(
        pool: asyncpg.Pool,
        session_id: str,
        role: str,
        content: str,
        citations: List[Dict] = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        feedback: str = 'no_feedback',
        latency_ms: int = 0,
        query_category: Optional[str] = None,
        query_category_confidence: Optional[float] = None,
        conversation_turn: Optional[int] = None
    ) -> Optional[str]:
        """
        Save a chat message to the chat_messages table.
        Includes query classification and conversation turn fields for analytics.
        """
        if not pool:
            logger.error("Database pool instance was not provided to save_chat_message.")
            return None

        try:
            query = """
                INSERT INTO chat_messages (
                    id, session_id, role, content, citations,
                    tokens_in, tokens_out, feedback, latency_ms,
                    query_category, query_category_confidence,
                    conversation_turn,
                    created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), $1::uuid, $2, $3, $4::jsonb,
                    $5, $6, $7, $8,
                    $9, $10,
                    $11,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                RETURNING id
            """

            async with pool.acquire() as conn:
                citations_json = json.dumps(citations if citations else [])

                async with conn.transaction():
                    result = await conn.fetchrow(
                        query,
                        session_id,
                        role,
                        content,
                        citations_json,
                        tokens_in,
                        tokens_out,
                        feedback,
                        latency_ms,
                        query_category,
                        query_category_confidence,
                        conversation_turn
                    )

                    # Also update session last_activity
                    await conn.execute(
                        "UPDATE chat_sessions SET last_activity = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = $1::uuid",
                        session_id
                    )

                if result:
                    message_id = str(result['id'])
                    log_extra = f", category: {query_category}" if query_category else ""
                    turn_extra = f", turn: {conversation_turn}" if conversation_turn else ""
                    logger.info(f"Message saved with ID: {message_id} (Role: {role}{log_extra}{turn_extra})")
                    return message_id
                return None

        except Exception as e:
            logger.error(f"Error saving chat message: {e}", exc_info=True)
            return None

    @staticmethod
    async def update_session_analytics(
        pool: asyncpg.Pool,
        session_id: str,
        device_type: Optional[str] = None,
        referrer: Optional[str] = None
    ) -> bool:
        """
        Update session with analytics data (device_type, referrer).
        Called when first chat message includes analytics data.
        """
        if not pool:
            return False

        try:
            # Build dynamic update query based on provided fields
            updates = []
            params = [session_id]
            param_idx = 2

            if device_type is not None:
                updates.append(f"device_type = ${param_idx}")
                params.append(device_type)
                param_idx += 1

            if referrer is not None:
                updates.append(f"referrer = ${param_idx}")
                params.append(referrer)
                param_idx += 1

            if not updates:
                return True  # Nothing to update

            updates.append("updated_at = CURRENT_TIMESTAMP")
            updates.append("last_activity = CURRENT_TIMESTAMP")

            query = f"""
                UPDATE chat_sessions
                SET {', '.join(updates)}
                WHERE id = $1::uuid
            """

            async with pool.acquire() as conn:
                result = await conn.execute(query, *params)
                if result == "UPDATE 1":
                    logger.info(f"Session {session_id} analytics updated (device: {device_type}, referrer: {referrer[:50] + '...' if referrer and len(referrer) > 50 else referrer})")
                    return True
                return False

        except Exception as e:
            logger.error(f"Error updating session analytics: {e}")
            return False

    @staticmethod
    async def update_message_feedback(pool: asyncpg.Pool, message_id: str, feedback: str) -> bool:
        """
        Update the feedback status of a message.
        """
        if not pool: return False

        try:
            query = """
                UPDATE chat_messages
                SET feedback = $2, updated_at = CURRENT_TIMESTAMP
                WHERE id = $1::uuid
            """

            async with pool.acquire() as conn:
                result = await conn.execute(query, message_id, feedback)
                # result is like "UPDATE 1"
                if result == "UPDATE 1":
                    logger.info(f"Feedback updated for message {message_id}")
                    return True
                return False

        except Exception as e:
            logger.error(f"Error updating feedback: {e}")
            return False

    @staticmethod
    async def create_detailed_feedback(
        pool: asyncpg.Pool, 
        message_id: str, 
        feedback_type: str,
        # comment: str = None, # Comment functionality removed
        ip_address: str = None,
        user_agent: str = None
    ) -> Optional[str]:
        """
        Create a detailed feedback entry.
        """
        if not pool: return None

        try:
            query = """
                INSERT INTO chat_feedbacks (
                    id, message_id, feedback_type, 
                    ip_address, user_agent, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), $1::uuid, $2, 
                    $3, $4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                RETURNING id
            """
            
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    query,
                    message_id,
                    feedback_type,
                    ip_address,
                    user_agent
                )
                
                if result:
                    feedback_id = str(result['id'])
                    logger.info(f"Detailed feedback saved: {feedback_id}")
                    return feedback_id
                return None

        except Exception as e:
            logger.error(f"Error creating detailed feedback: {e}")
            return None
