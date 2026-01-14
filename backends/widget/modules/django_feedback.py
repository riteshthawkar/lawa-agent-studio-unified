"""
Django Feedback Integration for Chatbot Backend
Handles feedback operations using Django ORM through the shared database.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from uuid import UUID
import asyncpg
from modules.django_database import DjangoDatabaseManager

logger = logging.getLogger(__name__)


class DjangoFeedbackService:
    """Service for handling feedback operations through Django database"""
    
    def __init__(self):
        self.django_db = DjangoDatabaseManager()
    
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
        Submit feedback for a chat message using Django ORM
        
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
        try:
            # Convert string UUID to UUID object
            message_uuid = UUID(message_id)
            
            # Use Django ORM to handle feedback
            result = await self.django_db.submit_feedback(
                message_id=message_uuid,
                feedback_type=feedback_type,
                user_id=user_id,
                comment=comment,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return {
                'success': True,
                'feedback_id': str(result['feedback_id']),
                'created': result['created'],
                'message': f"Feedback {'created' if result['created'] else 'updated'} successfully"
            }
            
        except ValueError as e:
            logger.error(f"Invalid message ID format: {message_id}")
            return {
                'success': False,
                'error': f"Invalid message ID format: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error submitting feedback: {str(e)}")
            return {
                'success': False,
                'error': f"Failed to submit feedback: {str(e)}"
            }
    
    async def get_message_feedback(self, message_id: str) -> Dict[str, Any]:
        """
        Get feedback information for a message
        
        Args:
            message_id: UUID of the chat message
            
        Returns:
            Dict with feedback information
        """
        try:
            message_uuid = UUID(message_id)
            
            result = await self.django_db.get_message_feedback(message_uuid)
            
            return {
                'success': True,
                'message_id': message_id,
                'current_feedback': result['current_feedback'],
                'feedback_counts': result['feedback_counts'],
                'recent_feedbacks': result['recent_feedbacks']
            }
            
        except ValueError as e:
            logger.error(f"Invalid message ID format: {message_id}")
            return {
                'success': False,
                'error': f"Invalid message ID format: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error getting message feedback: {str(e)}")
            return {
                'success': False,
                'error': f"Failed to get message feedback: {str(e)}"
            }
    
    async def get_session_feedback_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Get feedback statistics for a chat session
        
        Args:
            session_id: UUID of the chat session
            
        Returns:
            Dict with session feedback statistics
        """
        try:
            session_uuid = UUID(session_id)
            
            result = await self.django_db.get_session_feedback_stats(session_uuid)
            
            return {
                'success': True,
                'session_id': session_id,
                'stats': result
            }
            
        except ValueError as e:
            logger.error(f"Invalid session ID format: {session_id}")
            return {
                'success': False,
                'error': f"Invalid session ID format: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error getting session feedback stats: {str(e)}")
            return {
                'success': False,
                'error': f"Failed to get session feedback stats: {str(e)}"
            }


# Global instance
feedback_service = DjangoFeedbackService()
