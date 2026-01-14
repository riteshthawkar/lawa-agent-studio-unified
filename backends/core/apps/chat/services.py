import requests
import time
from django.conf import settings
from django.utils import timezone
from .models import ChatSession, ChatMessage
from apps.chatbot.models import Chatbot
from apps.core.exceptions import QuotaExceeded


class ChatbotService:
    """Service for interacting with external chatbot service"""
    
    def __init__(self):
        self.base_url = settings.CHATBOT_API_BASE
        self.api_token = settings.CHATBOT_API_TOKEN
        self.timeout = 30
    
    def send_message(self, session, user_message, chatbot):
        """Send message to external chatbot service and get response"""
        
        # Check quotas (simplified for MVP)
        # TODO: Implement proper quota checking
        
        default_model_provider = getattr(settings, 'CHATBOT_DEFAULT_MODEL_PROVIDER', 'openai')
        default_model_name = getattr(settings, 'CHATBOT_DEFAULT_MODEL_NAME', 'gpt-4o')
        default_retrieval_config = getattr(settings, 'CHATBOT_DEFAULT_RETRIEVAL_CONFIG', {})
        default_prompt_template = getattr(settings, 'CHATBOT_DEFAULT_PROMPT_TEMPLATE', '')
        default_safety_config = getattr(settings, 'CHATBOT_DEFAULT_SAFETY_CONFIG', {})

        # Prepare request payload
        # Read AI config from chatbot model (JSON field)
        ai_config = getattr(chatbot, 'config', {}) or {}
        
        payload = {
            'session_id': str(session.id),
            'user_message': user_message,
            'chatbot_config': {
                'model_provider': ai_config.get('model_provider', default_model_provider),
                'model_name': ai_config.get('model', default_model_name), # Frontend usually sends 'model' or 'model_name'
                'temperature': ai_config.get('temperature', 0.7),
                'system_prompt': ai_config.get('system_prompt', default_prompt_template),
                
                # Legacy/Advanced fields
                'retrieval_config': ai_config.get('retrieval_config', default_retrieval_config),
                'safety_config': ai_config.get('safety_config', default_safety_config),
            },
            'namespace': session.site.get_namespace() if hasattr(session, 'site') else None,
            'site_domain': session.site.domain if hasattr(session, 'site') else None,
        }
        
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
        }
        
        start_time = time.time()
        
        try:
            response = requests.post(
                f"{self.base_url}/chat",
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Extract response data
            assistant_message = result.get('message', '')
            citations = result.get('citations', [])
            tokens_in = result.get('tokens_in', 0)
            tokens_out = result.get('tokens_out', 0)
            
            return {
                'assistant_message': assistant_message,
                'citations': citations,
                'tokens_in': tokens_in,
                'tokens_out': tokens_out,
                'latency_ms': latency_ms
            }
            
        except requests.exceptions.RequestException as e:
            from apps.core.exceptions import ChatbotServiceException
            
            # Extract error message from response if available
            error_msg = str(e)
            status_code = 503
            
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                try:
                    error_json = e.response.json()
                    error_msg = error_json.get('detail') or error_json.get('message') or str(e)
                except ValueError:
                    # Not JSON
                    error_msg = e.response.text or str(e)
            
            raise ChatbotServiceException(error_msg, status_code=status_code)
    
    def create_session(self, chatbot, site, user_id=None, meta=None):
        """Create a new chat session"""
        session = ChatSession.objects.create(
            chatbot_id=chatbot.id,
            site_id=site.id,
            user_id=user_id,
            meta=meta or {}
        )
        return session
    
    def add_message(self, session, role, content, tokens_in=0, tokens_out=0, citations=None, latency_ms=0):
        """Add a message to a chat session"""
        message = ChatMessage.objects.create(
            session=session,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            citations=citations or [],
            latency_ms=latency_ms
        )
        return message
    
    def close_session(self, session):
        """Close a chat session"""
        session.closed_at = timezone.now()
        session.save()
        return session
