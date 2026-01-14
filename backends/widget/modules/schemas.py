from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class ChatRequest(BaseModel):
    """Request model for chat endpoints"""
    question: str = Field(..., max_length=1024)
    language: str
    # Use default_factory to avoid shared mutable defaults
    previous_chats: List[dict] = Field(default_factory=list)

    # Analytics fields
    conversation_turn: Optional[int] = Field(default=None, description="Turn number in conversation (1-indexed)")
    device_type: Optional[str] = Field(default=None, description="Device type: mobile, tablet, desktop, unknown")
    referrer: Optional[str] = Field(default=None, description="Page referrer URL")

class CitationSource(BaseModel):
    """Model for citation sources"""
    url: str
    cite_num: str 