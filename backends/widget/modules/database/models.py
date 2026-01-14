"""
Database models and schemas.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class Source(BaseModel):
    """Model for a citation source"""
    url: str
    cite_num: str


class ChatHistoryEntry(BaseModel):
    """Model for a chat history entry"""
    id: Optional[int] = None
    query: str
    response: str
    sources: List[Source] = []
    timestamp: Optional[datetime] = None
    feedback: Optional[str] = None
    id_str: Optional[str] = None  # String ID (UUID) for the chat entry
    rag_app_name: Optional[str] = None # Name of the RAG application
    
    class Config:
        from_attributes = True


class FeedbackUpdate(BaseModel):
    """Model for updating feedback on a chat history entry"""
    feedback: str = Field(..., pattern="^(like|dislike)$")


class ChatSession(BaseModel):
    """Model for a chat session (MVP version)"""
    id: Optional[UUID] = None
    site_id: Optional[UUID] = None
    chatbot_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    session_data: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str = Field(default="active", pattern="^(active|ended|timeout)$")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class SessionCreate(BaseModel):
    """Model for creating a new chat session"""
    site_id: Optional[UUID] = None
    chatbot_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    session_data: Dict[str, Any] = Field(default_factory=dict)


class SessionUpdate(BaseModel):
    """Model for updating a chat session"""
    session_data: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, pattern="^(active|ended|timeout)$")
    ended_at: Optional[datetime] = None
