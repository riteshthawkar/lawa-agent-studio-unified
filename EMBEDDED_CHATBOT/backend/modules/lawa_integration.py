#!/usr/bin/env python3
"""
LAWA Platform Integration Module
Handles Django database connection and API key validation for site-specific chatbots.
"""

import asyncio
import asyncpg
import logging
from typing import Optional, Dict, Any
from modules.config import (
    DB_HOST, DB_PORT, DB_NAME, 
    DB_USER, DB_PASSWORD, INTEGRATION_MODE
)

logger = logging.getLogger(__name__)

class LawaIntegration:
    """
    Integration layer for LAWA platform database access.
    Validates API keys and retrieves site information for namespace routing.
    """
    
    def __init__(self):
        self.pool = None
        self.enabled = INTEGRATION_MODE == "lawa"
        
    async def initialize(self):
        """Initialize database connection pool if in LAWA integration mode."""
        if not self.enabled:
            logger.info("LAWA integration disabled - running in legacy mode")
            return
            
        try:
            # Create connection string
            dsn = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            
            # Create connection pool - Production optimized
            self.pool = await asyncpg.create_pool(
                dsn,
                min_size=5,      # Increased for production
                max_size=20,     # Increased for production
                command_timeout=30,
                max_queries=50000,
                max_inactive_connection_lifetime=300.0,
                setup=self._setup_connection
            )
            
            logger.info(f"Connected to LAWA Django database at {DB_HOST}:{DB_PORT}/{DB_NAME}")
            
            # Test the connection
            await self._test_connection()
            
        except Exception as e:
            logger.error(f"Failed to connect to Django database: {e}")
            # Don't raise - allow fallback to legacy mode
            self.enabled = False
            logger.warning("Falling back to legacy mode due to database connection failure")
    
    async def _setup_connection(self, conn):
        """Setup connection with proper settings."""
        await conn.execute("SET timezone TO 'UTC'")
        await conn.execute("SET statement_timeout TO '30s'")
        await conn.execute("SET idle_in_transaction_session_timeout TO '15s'")
    
    async def _test_connection(self):
        """Test database connection and table access."""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Test if chatbots table exists and is accessible
                result = await conn.fetchval("SELECT COUNT(*) FROM chatbots LIMIT 1")
                logger.info(f"Database connection test successful - chatbots table has {result} records")
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            raise
    
    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("LAWA database connection pool closed")
    
    async def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Validate API key against Django chatbots table and return site information.

        Args:
            api_key: The chatbot API key to validate

        Returns:
            Dict with site_id, chatbot_id, site_domain, query_categories if valid, None if invalid
        """
        if not self.enabled or not self.pool:
            logger.debug("LAWA integration not enabled, API key validation skipped")
            return None

        try:
            async with self.pool.acquire() as conn:
                # Query chatbots table with JOIN to sites table for complete information
                query = """
                    SELECT
                        c.id as chatbot_id,
                        c.site_id,
                        c.name as chatbot_name,
                        c.status as chatbot_status,
                        c.config as chatbot_config,
                        c.chatbot_tone,
                        c.response_length,
                        c.description,
                        c.greeting_message,
                        c.primary_color,
                        c.text_color,
                        c.theme,
                        c.position,
                        c.placeholder_text,
                        s.domain as site_domain,
                        s.name as site_name,
                        s.status as site_status,
                        s.active_namespace
                    FROM chatbots c
                    JOIN sites s ON c.site_id = s.id
                    WHERE c.api_key = $1 AND c.status = 'active' AND s.status = 'active'
                """

                result = await conn.fetchrow(query, api_key)

                if result:
                    chatbot_id = str(result['chatbot_id'])

                    # Fetch query categories for this chatbot
                    categories = await self._get_query_categories(conn, chatbot_id)

                    # Extract special instructions from config JSONField
                    # Handle case where config might be returned as JSON string
                    chatbot_config = result['chatbot_config'] or {}
                    if isinstance(chatbot_config, str):
                        import json
                        try:
                            chatbot_config = json.loads(chatbot_config)
                        except json.JSONDecodeError:
                            chatbot_config = {}
                    special_instructions = chatbot_config.get('system_prompt', '') if isinstance(chatbot_config, dict) else ''
                    
                    # Use active namespace if available (supports zero-downtime re-indexing), fallback to default
                    namespace = result['active_namespace']
                    if not namespace:
                        namespace = f"site_{result['site_id']}"

                    site_info = {
                        'chatbot_id': chatbot_id,
                        'site_id': str(result['site_id']),
                        'chatbot_name': result['chatbot_name'],
                        'site_domain': result['site_domain'],
                        'site_name': result['site_name'],
                        'namespace': namespace,
                        'query_categories': categories,
                        'description': result['description'] or '',
                        'greeting_message': result['greeting_message'] or 'Hello! How can I help you today?',
                        'primary_color': result['primary_color'] or '#2563eb',
                        'text_color': result['text_color'] or '#ffffff',
                        'theme': result['theme'] or 'auto',
                        'position': result['position'] or 'bottom-right',
                        'placeholder_text': result['placeholder_text'] or 'Type your message...',
                        'chatbot_config': {
                            'special_instructions': special_instructions,
                            'chatbot_tone': result['chatbot_tone'],
                            'response_length': result['response_length']
                        }
                    }

                    logger.info(f"API key validated for site: {site_info['site_domain']} (namespace: {site_info['namespace']}, categories: {len(categories)}, tone: {result['chatbot_tone']}, length: {result['response_length']})")
                    return site_info
                else:
                    logger.warning(f"Invalid or inactive API key: {api_key[:10]}...")
                    return None

        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return None

    async def _get_query_categories(self, conn, chatbot_id: str) -> list:
        """
        Get active query categories for a chatbot.

        Args:
            conn: Database connection
            chatbot_id: UUID of the chatbot

        Returns:
            List of category dictionaries with name, description, keywords
        """
        try:
            query = """
                SELECT id, name, description, keywords
                FROM query_categories
                WHERE chatbot_id = $1 AND is_active = true
                ORDER BY display_order, name
            """

            rows = await conn.fetch(query, chatbot_id)

            categories = []
            for row in rows:
                categories.append({
                    'id': str(row['id']),
                    'name': row['name'],
                    'description': row['description'] or '',
                    'keywords': row['keywords'] or []
                })

            return categories

        except Exception as e:
            logger.warning(f"Error fetching query categories: {e}")
            return []
    
    async def get_site_info(self, site_id: str) -> Optional[Dict[str, Any]]:
        """
        Get site information by site_id.
        
        Args:
            site_id: UUID of the site
            
        Returns:
            Dict with site information if found, None otherwise
        """
        if not self.enabled or not self.pool:
            return None
            
        try:
            async with self.pool.acquire() as conn:
                query = """
                    SELECT id, domain, status, last_indexed_at, created_at, active_namespace
                    FROM sites 
                    WHERE id = $1 AND status = 'active'
                """
                
                result = await conn.fetchrow(query, site_id)
                
                if result:
                    # Use active namespace if available, fallback to default
                    namespace = result['active_namespace']
                    if not namespace:
                        namespace = f"site_{result['id']}"
                        
                    return {
                        'site_id': str(result['id']),
                        'domain': result['domain'],
                        'status': result['status'],
                        'last_indexed_at': result['last_indexed_at'],
                        'namespace': namespace
                    }
                else:
                    logger.warning(f"Site not found or inactive: {site_id}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting site info: {e}")
            return None
    
    async def submit_feedback(
        self, 
        message_id: str, 
        feedback_type: str, 
        user_id: Optional[str] = None,
        comment: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submit feedback for a chat message.
        
        Args:
            message_id: UUID of the chat message
            feedback_type: 'like' or 'dislike'
            user_id: Optional user ID
            comment: Optional feedback comment
            ip_address: Optional client IP address
            user_agent: Optional user agent string
            
        Returns:
            Dict with feedback submission result
        """
        if not self.enabled or not self.pool:
            return {'success': False, 'error': 'LAWA integration not enabled'}
            
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # First, check if the message exists and is an assistant message
                    message_query = """
                        SELECT id, role FROM chat_messages 
                        WHERE id = $1 AND role = 'assistant'
                    """
                    message_result = await conn.fetchrow(message_query, message_id)
                    
                    if not message_result:
                        return {'success': False, 'error': 'Message not found or not an assistant message'}
                    
                    # Check if feedback already exists
                    existing_feedback_query = """
                        SELECT id FROM chat_feedbacks 
                        WHERE message_id = $1 AND (user_id = $2 OR (user_id IS NULL AND ip_address = $3))
                    """
                    existing = await conn.fetchrow(
                        existing_feedback_query, 
                        message_id, 
                        user_id, 
                        ip_address
                    )
                    
                    if existing:
                        # Update existing feedback
                        update_query = """
                            UPDATE chat_feedbacks 
                            SET feedback_type = $1, comment = $2, user_agent = $3, updated_at = CURRENT_TIMESTAMP
                            WHERE id = $4
                        """
                        await conn.execute(
                            update_query, 
                            feedback_type, 
                            comment, 
                            user_agent, 
                            existing['id']
                        )
                        feedback_id = existing['id']
                        created = False
                    else:
                        # Create new feedback
                        insert_query = """
                            INSERT INTO chat_feedbacks (id, message_id, feedback_type, user_id, comment, ip_address, user_agent, created_at, updated_at)
                            VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            RETURNING id
                        """
                        result = await conn.fetchrow(
                            insert_query, 
                            message_id, 
                            feedback_type, 
                            user_id, 
                            comment, 
                            ip_address, 
                            user_agent
                        )
                        feedback_id = result['id']
                        created = True
                    
                    # Update the message's feedback field
                    update_message_query = """
                        UPDATE chat_messages 
                        SET feedback = $1, updated_at = CURRENT_TIMESTAMP
                        WHERE id = $2
                    """
                    await conn.execute(update_message_query, feedback_type, message_id)
                    
                    return {
                        'success': True,
                        'feedback_id': str(feedback_id),
                        'created': created
                    }
                    
        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            return {'success': False, 'error': f'Failed to submit feedback: {str(e)}'}
    
    async def get_message_feedback(self, message_id: str) -> Dict[str, Any]:
        """
        Get feedback information for a message.
        
        Args:
            message_id: UUID of the chat message
            
        Returns:
            Dict with feedback information
        """
        if not self.enabled or not self.pool:
            return {'success': False, 'error': 'LAWA integration not enabled'}
            
        try:
            async with self.pool.acquire() as conn:
                # Get message feedback field
                message_query = """
                    SELECT feedback FROM chat_messages WHERE id = $1
                """
                message_result = await conn.fetchrow(message_query, message_id)
                
                if not message_result:
                    return {'success': False, 'error': 'Message not found'}
                
                # Get feedback counts
                counts_query = """
                    SELECT 
                        COUNT(*) FILTER (WHERE feedback_type = 'like') as like_count,
                        COUNT(*) FILTER (WHERE feedback_type = 'dislike') as dislike_count,
                        COUNT(*) as total_count
                    FROM chat_feedbacks 
                    WHERE message_id = $1
                """
                counts_result = await conn.fetchrow(counts_query, message_id)
                
                # Get recent feedbacks
                recent_query = """
                    SELECT id, feedback_type, user_id, comment, created_at
                    FROM chat_feedbacks 
                    WHERE message_id = $1
                    ORDER BY created_at DESC
                    LIMIT 10
                """
                recent_feedbacks = await conn.fetch(recent_query, message_id)
                
                return {
                    'success': True,
                    'current_feedback': message_result['feedback'],
                    'feedback_counts': {
                        'like': counts_result['like_count'],
                        'dislike': counts_result['dislike_count'],
                        'total': counts_result['total_count']
                    },
                    'recent_feedbacks': [
                        {
                            'id': str(fb['id']),
                            'feedback_type': fb['feedback_type'],
                            'user_id': str(fb['user_id']) if fb['user_id'] else None,
                            'comment': fb['comment'],
                            'created_at': fb['created_at'].isoformat()
                        }
                        for fb in recent_feedbacks
                    ]
                }
                
        except Exception as e:
            logger.error(f"Error getting message feedback: {e}")
            return {'success': False, 'error': f'Failed to get message feedback: {str(e)}'}
    
    async def get_session_feedback_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Get feedback statistics for a chat session.
        
        Args:
            session_id: UUID of the chat session
            
        Returns:
            Dict with session feedback statistics
        """
        if not self.enabled or not self.pool:
            return {'success': False, 'error': 'LAWA integration not enabled'}
            
        try:
            async with self.pool.acquire() as conn:
                # Get message feedback statistics
                message_stats_query = """
                    SELECT 
                        COUNT(*) as total_messages,
                        COUNT(*) FILTER (WHERE feedback = 'like') as liked_messages,
                        COUNT(*) FILTER (WHERE feedback = 'dislike') as disliked_messages,
                        COUNT(*) FILTER (WHERE feedback = 'no_feedback') as no_feedback_messages
                    FROM chat_messages 
                    WHERE session_id = $1 AND role = 'assistant'
                """
                message_stats = await conn.fetchrow(message_stats_query, session_id)
                
                # Get total feedback counts
                total_feedback_query = """
                    SELECT 
                        COUNT(*) FILTER (WHERE feedback_type = 'like') as total_likes,
                        COUNT(*) FILTER (WHERE feedback_type = 'dislike') as total_dislikes
                    FROM chat_feedbacks cf
                    JOIN chat_messages cm ON cf.message_id = cm.id
                    WHERE cm.session_id = $1
                """
                total_feedback = await conn.fetchrow(total_feedback_query, session_id)
                
                total_messages = message_stats['total_messages'] or 0
                feedback_rate = 0
                if total_messages > 0:
                    feedback_rate = (message_stats['liked_messages'] + message_stats['disliked_messages']) / total_messages
                
                return {
                    'success': True,
                    'total_messages': total_messages,
                    'message_feedback': {
                        'liked': message_stats['liked_messages'] or 0,
                        'disliked': message_stats['disliked_messages'] or 0,
                        'no_feedback': message_stats['no_feedback_messages'] or 0
                    },
                    'total_feedback': {
                        'likes': total_feedback['total_likes'] or 0,
                        'dislikes': total_feedback['total_dislikes'] or 0,
                        'total': (total_feedback['total_likes'] or 0) + (total_feedback['total_dislikes'] or 0)
                    },
                    'feedback_rate': feedback_rate
                }
                
        except Exception as e:
            logger.error(f"Error getting session feedback stats: {e}")
            return {'success': False, 'error': f'Failed to get session feedback stats: {str(e)}'}

# Global instance
lawa_integration = LawaIntegration()

async def initialize_lawa_integration():
    """Initialize the global LAWA integration instance."""
    await lawa_integration.initialize()

async def close_lawa_integration():
    """Close the global LAWA integration instance."""
    await lawa_integration.close()
