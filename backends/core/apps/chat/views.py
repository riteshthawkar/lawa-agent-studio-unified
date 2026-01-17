from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from .models import ChatSession, ChatMessage, ChatFeedback
from .serializers import (
    ChatSessionSerializer, ChatMessageSerializer, ChatFeedbackSerializer,
    FeedbackUpdateSerializer, MessageFeedbackSerializer
)
from .services import ChatbotService
from apps.chatbot.models import Chatbot
from apps.sites.models import Site
from apps.core.views import BaseViewSet
from apps.core.organization_permissions import (
    check_chatbot_access,
    check_site_access,
    check_session_access,
    OrganizationAccessError,
    ResourceNotInOrganizationError
)
import logging

logger = logging.getLogger(__name__)


class ChatSessionViewSet(BaseViewSet):
    """Chat session management"""
    queryset = ChatSession.objects.all()
    serializer_class = ChatSessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Get chat sessions for the current user's organization.
        Sessions are linked to sites via site_id, and sites have org_id.
        We filter sessions by joining through site to match org_id.

        Query params:
        - days: Filter sessions from last N days (default: no filter)
        - limit: Override pagination limit (max 1000)
        """
        from datetime import timedelta
        from django.utils import timezone
        request = self.request

        # Get user's organizations
        from apps.core.organization_permissions import get_user_organizations
        user_orgs = get_user_organizations(request.user)

        # Filter sessions where the related site belongs to one of the user's organizations
        # This prevents leaking all sessions if org_id is missing from request
        queryset = self.queryset.filter(site__org_id__in=user_orgs.values('id'))

        # Filter by days if specified
        days = request.query_params.get('days')
        if days:
            try:
                days = int(days)
                start_date = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(started_at__gte=start_date)
            except (ValueError, TypeError):
                pass

        # Order by most recent first
        return queryset.select_related('site', 'chatbot').order_by('-started_at')

    def list(self, request, *args, **kwargs):
        """Override list to support custom limit parameter."""
        # Check if custom limit is requested
        limit = request.query_params.get('limit')
        if limit:
            try:
                limit = min(int(limit), 1000)  # Cap at 1000
                queryset = self.filter_queryset(self.get_queryset())[:limit]
                serializer = self.get_serializer(queryset, many=True)
                return Response({
                    'results': serializer.data,
                    'count': len(serializer.data)
                })
            except (ValueError, TypeError):
                pass

        # Default pagination behavior
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Create new chat session"""
        chatbot_id = request.data.get('chatbot_id')
        site_id = request.data.get('site_id')
        meta = request.data.get('meta', {})

        if not chatbot_id or not site_id:
            return Response(
                {'error': 'chatbot_id and site_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Validate user has access to this chatbot and site
            chatbot = check_chatbot_access(request.user, chatbot_id)
            site = check_site_access(request.user, site_id)

            # Verify chatbot belongs to the site
            if str(chatbot.site_id) != str(site_id):
                return Response(
                    {'error': 'Chatbot does not belong to the specified site'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except (OrganizationAccessError, ResourceNotInOrganizationError) as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )

        # Extract referrer from request or meta
        referrer = request.data.get('referrer')
        if not referrer and meta:
            referrer = meta.get('page_url') or meta.get('referrer')

        # Create session
        chatbot_service = ChatbotService()
        session = chatbot_service.create_session(
            chatbot=chatbot,
            site=site,
            user_id=request.user.id if request.user.is_authenticated else None,
            meta=meta,
            referrer=referrer
        )

        return Response({
            'session_id': str(session.id),
            'session_key': session.session_key,
            'chatbot_id': str(chatbot.id),
            'site_id': str(site.id),
            'created_at': session.created_at
        }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_message(request, session_id):
    """Send a message in a chat session"""
    # Validate user has access to this session
    session = check_session_access(request.user, session_id)

    user_content = request.data.get('content', '')
    if not user_content:
        return Response(
            {'error': 'Message content is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get chatbot
    chatbot = get_object_or_404(Chatbot, id=session.chatbot_id)
    
    # Create user message
    user_message = ChatMessage.objects.create(
        session=session,
        role='user',
        content=user_content
    )
    
    # Send to chatbot service
    # Note: ChatbotServiceException is now handled by custom_exception_handler
    chatbot_service = ChatbotService()
    response = chatbot_service.send_message(
        session=session,
        user_message=user_content,
        chatbot=chatbot
    )
    
    # Create assistant message
    assistant_message = ChatMessage.objects.create(
        session=session,
        role='assistant',
        content=response['assistant_message'],
        tokens_in=response['tokens_in'],
        tokens_out=response['tokens_out'],
        citations=response['citations'],
        latency_ms=response['latency_ms']
    )
    
    return Response({
        'assistant_message': assistant_message.content,
        'citations': assistant_message.citations,
        'tokens_in': assistant_message.tokens_in,
        'tokens_out': assistant_message.tokens_out,
        'latency_ms': assistant_message.latency_ms
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def session_messages(request, session_id):
    """Get messages for a chat session"""
    # Validate user has access to this session
    session = check_session_access(request.user, session_id)

    messages = ChatMessage.objects.filter(session=session).order_by('created_at')

    return Response([{
        'id': str(msg.id),
        'role': msg.role,
        'content': msg.content,
        'created_at': msg.created_at,
        'citations': msg.citations,
        'tokens_in': msg.tokens_in,
        'tokens_out': msg.tokens_out,
        'latency_ms': msg.latency_ms
    } for msg in messages])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def close_session(request, session_id):
    """Close a chat session"""
    # Validate user has access to this session
    session = check_session_access(request.user, session_id)

    # Close session using service
    chatbot_service = ChatbotService()
    chatbot_service.close_session(session)
    
    return Response({'message': 'Session closed successfully'})


@api_view(['POST'])
@permission_classes([AllowAny])  # Allow anonymous feedback
def submit_feedback(request, message_id):
    """Submit feedback for a chat message"""
    message = get_object_or_404(ChatMessage, id=message_id)
    
    # Only allow feedback on assistant messages
    if message.role != 'assistant':
        return Response(
            {'error': 'Feedback can only be submitted on assistant messages'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    serializer = FeedbackUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    feedback_data = serializer.validated_data
    feedback_type = feedback_data['feedback_type']
    
    # Get client info
    client_ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    user_id = request.user.id if request.user.is_authenticated else None
    
    with transaction.atomic():
        # Create or update feedback
        feedback, created = ChatFeedback.objects.update_or_create(
            message=message,
            user_id=user_id,
            ip_address=client_ip if not user_id else None,
            defaults={
                'feedback_type': feedback_type,
                'user_agent': user_agent
            }
        )
        
        # Update message feedback field
        message.feedback = feedback_type
        message.save(update_fields=['feedback'])
    
    action = 'created' if created else 'updated'
    return Response({
        'message': f'Feedback {action} successfully',
        'feedback_id': str(feedback.id),
        'feedback_type': feedback_type,
        'created': created
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def message_feedback(request, message_id):
    """Get feedback information for a message"""
    message = get_object_or_404(ChatMessage, id=message_id)
    
    # Get feedback counts
    feedback_counts = {
        'like': message.feedbacks.filter(feedback_type='like').count(),
        'dislike': message.feedbacks.filter(feedback_type='dislike').count(),
        'total': message.feedbacks.count()
    }
    
    # Get recent feedbacks (limit to 10)
    recent_feedbacks = message.feedbacks.order_by('-created_at')[:10]
    feedback_serializer = ChatFeedbackSerializer(recent_feedbacks, many=True)
    
    return Response({
        'message_id': str(message.id),
        'current_feedback': message.feedback,
        'feedback_counts': feedback_counts,
        'recent_feedbacks': feedback_serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def session_feedback_stats(request, session_id):
    """Get feedback statistics for a chat session"""
    session = get_object_or_404(ChatSession, id=session_id)

    # Validate user has access to this session
    check_session_access(request.user, session_id)
    
    # Get all assistant messages in the session
    assistant_messages = ChatMessage.objects.filter(
        session=session, 
        role='assistant'
    )
    
    # Calculate feedback statistics
    total_messages = assistant_messages.count()
    liked_messages = assistant_messages.filter(feedback='like').count()
    disliked_messages = assistant_messages.filter(feedback='dislike').count()
    no_feedback_messages = assistant_messages.filter(feedback='no_feedback').count()
    
    # Get detailed feedback counts
    total_likes = ChatFeedback.objects.filter(
        message__session=session,
        feedback_type='like'
    ).count()
    
    total_dislikes = ChatFeedback.objects.filter(
        message__session=session,
        feedback_type='dislike'
    ).count()
    
    return Response({
        'session_id': str(session.id),
        'total_messages': total_messages,
        'message_feedback': {
            'liked': liked_messages,
            'disliked': disliked_messages,
            'no_feedback': no_feedback_messages
        },
        'total_feedback': {
            'likes': total_likes,
            'dislikes': total_dislikes,
            'total': total_likes + total_dislikes
        },
        'feedback_rate': (liked_messages + disliked_messages) / total_messages if total_messages > 0 else 0
    })


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
