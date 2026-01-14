from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.translation import gettext_lazy as _
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.db.models import Q
from django.utils import timezone
from urllib.parse import urlparse
import logging
import os

from .models import Chatbot, ConversationStarter, QueryCategory
from .serializers import (
    ChatbotSerializer,
    ChatbotCreateSerializer,
    IndexInfoSerializer,
    ChatbotIndexInfoSerializer,
    ConversationStarterSerializer,
    ConversationStarterCreateSerializer,
    ConversationStarterBulkSerializer,
    QueryCategorySerializer,
    QueryCategoryCreateSerializer,
    QueryCategoryBulkSerializer,
    QueryCategoryListSerializer
)
from apps.core.views import BaseViewSet
from apps.core.organization_permissions import check_chatbot_access
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.usage.services import QuotaService, QuotaLimitExceeded
from django.conf import settings

logger = logging.getLogger(__name__)


class ChatbotViewSet(BaseViewSet):
    """Chatbot management"""
    queryset = Chatbot.objects.all()
    serializer_class = ChatbotSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = ['status', 'site']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering_fields = ['created_at', 'name']
    ordering = ['-created_at']

    # Use StandardResultsSetPagination from core if available, else PageNumberPagination
    # Assuming explicit pagination is needed if defaults are not working
    class StandardPagination(PageNumberPagination):
        page_size = 10
        page_size_query_param = 'page_size'
        max_page_size = 100
        
    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ChatbotCreateSerializer
        return ChatbotSerializer

    def get_queryset(self):
        """Get all chatbots for user's organizations"""
        if getattr(self, 'swagger_fake_view', False):
            return Chatbot.objects.none()
            
        request = self.request
        if not request.user.is_authenticated:
            return Chatbot.objects.none()
            
        from apps.core.organization_permissions import get_user_organizations
        user_orgs = get_user_organizations(request.user)
        
        return Chatbot.objects.filter(site__org_id__in=user_orgs.values('id'))

    def create(self, request, *args, **kwargs):
        """Create new chatbot with quota enforcement"""
        site_id = self.kwargs.get('site_id')
        if not site_id:
            return Response(
                {'error': 'Site ID required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        
        # Get site - enforce organization access
        site = get_object_or_404(Site, id=site_id, org__users=request.user)
        
        # Enforce chatbot limit
        if site.org_id:
            try:
                QuotaService.enforce_chatbot_limit(site.org_id)
            except QuotaLimitExceeded as e:
                return Response(
                    {'error': e.message, 'limit_type': e.limit_type},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create chatbot - simplified for MVP (no org_id)
        chatbot = serializer.save(
            site=site
        )
        
        return Response(
            ChatbotSerializer(chatbot).data,
            status=status.HTTP_201_CREATED
        )



# Rate limiting classes
class ChatbotThrottle(UserRateThrottle):
    scope = 'chatbot'

class ChatbotAnonThrottle(AnonRateThrottle):
    scope = 'chatbot_anon'


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([ChatbotThrottle, ChatbotAnonThrottle])
def chatbot_index_info(request):
    """
    GET /chatbot/index-info/ — Get indexing information for chatbot backend
    
    This endpoint is used by the chatbot backend to retrieve indexing information
    when a user asks a query from an embedded chatbot on their website.
    """
    logger.info(f"Chatbot index info request from IP: {request.META.get('REMOTE_ADDR')}")
    
    # Get query parameters
    domain = request.GET.get('domain')
    api_key = request.GET.get('api_key')
    
    if not domain or not api_key:
        return Response(
            {
                'error': 'Missing required parameters: domain and api_key',
                'code': 'MISSING_PARAMETERS'
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Authenticate using API key
        chatbot = get_object_or_404(Chatbot, api_key=api_key, status='active')
        
        # Parse domain to get clean domain
        parsed_url = urlparse(domain)
        clean_domain = f"{parsed_url.scheme}://{parsed_url.netloc}" if parsed_url.scheme else f"https://{parsed_url.netloc}"
        
        # Find site by domain - simplified for MVP (no organization filtering)
        site = Site.objects.filter(
            domain__iexact=clean_domain,
            status='active'
        ).first()
        
        if not site:
            logger.warning(f"Site not found for domain: {clean_domain}, chatbot: {chatbot.id}")
            return Response(
                {
                    'error': 'Site not found or not active',
                    'code': 'SITE_NOT_FOUND'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # SECURITY FIX: Ensure site belongs to the same organization as the chatbot
        # The chatbot is linked to a site (source of truth for org)
        if site.org_id != chatbot.site.org_id:
            logger.warning(f"Cross-org access attempt: Chatbot {chatbot.id} (Org {chatbot.site.org_id}) tried to access Site {site.id} (Org {site.org_id})")
            return Response(
                {
                    'error': 'Site not found', # Mask existence
                    'code': 'SITE_NOT_FOUND'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get latest indexing job for the site
        latest_job = IndexingJob.objects.filter(
            site_id=site.id,
            status='completed'
        ).order_by('-completed_at').first()
        
        # Calculate namespace - use active_namespace from DB (set by indexer with timestamp)
        # This matches the format: site_{uuid}_{timestamp} used during indexing
        namespace = site.active_namespace or f"site_{site.id}"
        
        # Prepare response data - simplified for MVP
        site_data = {
            'id': str(site.id),
            'domain': site.domain,
            'status': site.status,
            'last_indexed_at': site.last_indexed_at.isoformat() if site.last_indexed_at else None
        }
        
        pinecone_index = getattr(settings, 'PINECONE_INDEX_NAME', os.getenv('PINECONE_INDEX', 'lawa-website-index'))
        embed_model = getattr(settings, 'CHATBOT_DEFAULT_EMBED_MODEL', os.getenv('EMBED_MODEL', 'sentence-transformers/all-MiniLM-L6-v2'))

        indexing_info = {
            'pinecone_index': pinecone_index,
            'namespace': namespace,
            'namespace_prefix': 'website_domain',
            'use_namespaces': True,
            'embed_model': embed_model,
            'total_documents': latest_job.documents_indexed if latest_job else 0,
            'last_indexed_at': latest_job.completed_at.isoformat() if latest_job and latest_job.completed_at else None
        }

        chatbot_config = {
            'chatbot_id': str(chatbot.id),
            'name': chatbot.name,
            'status': chatbot.status,
            'model': getattr(settings, 'CHATBOT_DEFAULT_MODEL_NAME', 'gpt-4o'),
            'temperature': 0.7,  # Fixed for MVP
            'max_tokens': 1000  # Fixed for MVP
        }
        
        api_endpoints = {
            'chat_session_create': '/v1/chat/sessions/',
            'chat_message_send': '/v1/chat/messages/',
            'indexing_status': f'/v1/tasks/{latest_job.task_id}/' if latest_job and latest_job.task_id else None
        }
        
        response_data = {
            'site': site_data,
            'indexing_info': indexing_info,
            'chatbot_config': chatbot_config,
            'api_endpoints': api_endpoints
        }
        
        logger.info(f"Successfully retrieved index info for domain: {clean_domain}, chatbot: {chatbot.id}")
        
        return Response(response_data)
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error retrieving chatbot index info: {str(e)}", exc_info=True)
        return Response(
            {
                'error': 'Internal server error',
                'code': 'INTERNAL_ERROR'
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chatbot_embed_code(request, chatbot_id):
    """
    GET /chatbots/{chatbot_id}/embed-code/ — Get embed code for chatbot
    
    Requires organization access validation.
    """
    # Validate organization access
    chatbot = check_chatbot_access(request.user, chatbot_id)
    
    return Response({
        'embed_code': chatbot.embed_code,
        'api_key': chatbot.api_key,
        'websocket_url': chatbot.get_websocket_url(),
        'widget_preview_url': chatbot.widget_preview_url
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_api_key(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/regenerate-api-key/ — Regenerate API key for chatbot
    
    Requires organization access validation.
    """
    # Validate organization access
    chatbot = check_chatbot_access(request.user, chatbot_id)
    
    # Regenerate API key and embed code
    chatbot.api_key = chatbot.generate_api_key()
    chatbot.embed_code = chatbot.generate_embed_code()
    chatbot.save()
    
    logger.info(
        "API key regenerated",
        extra={'chatbot_id': str(chatbot_id), 'user_id': str(request.user.id)}
    )
    
    return Response({
        'api_key': chatbot.api_key,
        'embed_code': chatbot.embed_code,
        'websocket_url': chatbot.get_websocket_url(),
        'message': 'API key and embed code regenerated successfully'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_embed_code(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/regenerate-embed-code/ — Regenerate embed code for chatbot
    
    Requires organization access validation.
    """
    # Validate organization access
    chatbot = check_chatbot_access(request.user, chatbot_id)
    
    # Regenerate only the embed code (keeping the same API key)
    new_embed_code = chatbot.regenerate_embed_code()
    
    logger.info(
        "Embed code regenerated",
        extra={'chatbot_id': str(chatbot_id), 'user_id': str(request.user.id)}
    )
    
    return Response({
        'embed_code': new_embed_code,
        'api_key': chatbot.api_key,
        'websocket_url': chatbot.get_websocket_url(),
        'widget_preview_url': chatbot.widget_preview_url,
        'message': 'Embed code regenerated successfully'
    })


# ==========================================
# Conversation Starters Views
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_conversation_starters(request, chatbot_id):
    """
    GET /chatbots/{chatbot_id}/starters/ — List conversation starters for a chatbot

    Returns all conversation starters for the specified chatbot,
    optionally filtered by active status.

    Query Parameters:
    - active_only: boolean - Filter to only active starters (default: false)
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    starters = ConversationStarter.objects.filter(chatbot=chatbot)

    # Filter by active status if requested
    active_only = request.GET.get('active_only', 'false').lower() == 'true'
    if active_only:
        starters = starters.filter(is_active=True)

    starters = starters.order_by('display_order', '-created_at')

    # Get stats
    stats = {
        'total': starters.count(),
        'active': starters.filter(is_active=True).count(),
        'auto_generated': starters.filter(is_auto_generated=True).count(),
        'total_clicks': sum(s.click_count for s in starters)
    }

    serializer = ConversationStarterSerializer(starters, many=True)

    return Response({
        'results': serializer.data,
        'stats': stats
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_conversation_starter(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/starters/ — Create a new conversation starter

    Request Body:
    - question: string (required) - The starter question text
    - category: string (optional) - Category for grouping
    - display_order: int (optional) - Display order (default: 0)
    - is_active: boolean (optional) - Whether active (default: true)
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    serializer = ConversationStarterCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    starter = ConversationStarter.objects.create(
        chatbot=chatbot,
        **serializer.validated_data
    )

    logger.info(
        f"Created conversation starter for chatbot {chatbot_id}",
        extra={'chatbot_id': str(chatbot_id), 'starter_id': str(starter.id)}
    )

    return Response(
        ConversationStarterSerializer(starter).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_create_starters(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/starters/bulk/ — Bulk create conversation starters

    Request Body:
    - starters: array of starter objects with question, category, display_order, is_active
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    serializer = ConversationStarterBulkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    created_starters = []
    for starter_data in serializer.validated_data['starters']:
        starter = ConversationStarter.objects.create(
            chatbot=chatbot,
            **starter_data
        )
        created_starters.append(starter)

    logger.info(
        f"Bulk created {len(created_starters)} conversation starters for chatbot {chatbot_id}",
        extra={'chatbot_id': str(chatbot_id), 'count': len(created_starters)}
    )

    return Response({
        'message': f'Successfully created {len(created_starters)} conversation starters',
        'starters': ConversationStarterSerializer(created_starters, many=True).data
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def conversation_starter_detail(request, starter_id):
    """
    GET/PUT/DELETE /starters/{starter_id}/ — Manage individual conversation starter
    """
    try:
        starter = ConversationStarter.objects.select_related('chatbot').get(id=starter_id)
    except ConversationStarter.DoesNotExist:
        return Response(
            {'error': 'Conversation starter not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, starter.chatbot_id)

    if request.method == 'GET':
        return Response(ConversationStarterSerializer(starter).data)

    elif request.method == 'PUT':
        serializer = ConversationStarterCreateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        for key, value in serializer.validated_data.items():
            setattr(starter, key, value)
        starter.save()

        logger.info(f"Updated conversation starter {starter_id}")
        return Response(ConversationStarterSerializer(starter).data)

    elif request.method == 'DELETE':
        starter.delete()
        logger.info(f"Deleted conversation starter {starter_id}")
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_starter(request, starter_id):
    """
    POST /starters/{starter_id}/toggle/ — Toggle active status of a conversation starter
    """
    try:
        starter = ConversationStarter.objects.select_related('chatbot').get(id=starter_id)
    except ConversationStarter.DoesNotExist:
        return Response(
            {'error': 'Conversation starter not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, starter.chatbot_id)

    starter.is_active = not starter.is_active
    starter.save(update_fields=['is_active'])

    logger.info(f"Toggled conversation starter {starter_id} to {'active' if starter.is_active else 'inactive'}")

    return Response({
        'id': str(starter.id),
        'is_active': starter.is_active,
        'message': f'Starter {"activated" if starter.is_active else "deactivated"}'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reorder_starters(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/starters/reorder/ — Reorder conversation starters

    Request Body:
    - order: array of {id, display_order} objects
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    order_data = request.data.get('order', [])
    if not isinstance(order_data, list):
        return Response(
            {'error': 'Order must be a list'},
            status=status.HTTP_400_BAD_REQUEST
        )

    updated_count = 0
    for item in order_data:
        starter_id = item.get('id')
        display_order = item.get('display_order')

        if starter_id and display_order is not None:
            try:
                starter = ConversationStarter.objects.get(
                    id=starter_id,
                    chatbot=chatbot
                )
                starter.display_order = int(display_order)
                starter.save(update_fields=['display_order'])
                updated_count += 1
            except (ConversationStarter.DoesNotExist, ValueError):
                continue

    logger.info(f"Reordered {updated_count} conversation starters for chatbot {chatbot_id}")

    return Response({
        'message': f'Successfully reordered {updated_count} starters',
        'updated_count': updated_count
    })


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([ChatbotThrottle, ChatbotAnonThrottle])
def track_starter_click(request, starter_id):
    """
    POST /starters/{starter_id}/click/ — Track when a user clicks a conversation starter

    This is a public endpoint that can be called from the embedded widget.

    Request Body (optional):
    - api_key: string - Chatbot API key for validation
    """
    try:
        starter = ConversationStarter.objects.select_related('chatbot').get(id=starter_id)
    except ConversationStarter.DoesNotExist:
        return Response(
            {'error': 'Conversation starter not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Optional API key validation for security
    api_key = request.data.get('api_key') or request.GET.get('api_key')
    if api_key and starter.chatbot.api_key != api_key:
        return Response(
            {'error': 'Invalid API key'},
            status=status.HTTP_403_FORBIDDEN
        )

    starter.increment_click()

    return Response({
        'click_count': starter.click_count,
        'message': 'Click tracked'
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([ChatbotThrottle, ChatbotAnonThrottle])
def public_starters(request, api_key):
    """
    GET /chatbot/{api_key}/starters/ — Get active conversation starters for a chatbot (public)

    This is a public endpoint used by the embedded widget to get conversation starters.
    """
    try:
        chatbot = Chatbot.objects.get(api_key=api_key, status='active')
    except Chatbot.DoesNotExist:
        return Response(
            {'error': 'Chatbot not found or inactive'},
            status=status.HTTP_404_NOT_FOUND
        )

    starters = ConversationStarter.objects.filter(
        chatbot=chatbot,
        is_active=True
    ).order_by('display_order', '-created_at')[:10]  # Limit to 10 starters

    # Simplified response for widget
    result = []
    for starter in starters:
        result.append({
            'id': str(starter.id),
            'question': starter.question,
            'category': starter.category
        })

    return Response({
        'starters': result,
        'chatbot_name': chatbot.name
    })


# ==========================================
# Query Category Views
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_query_categories(request, chatbot_id):
    """
    GET /chatbots/{chatbot_id}/categories/ — List query categories for a chatbot

    Returns all query categories defined for the specified chatbot.

    Query Parameters:
    - active_only: boolean - Filter to only active categories (default: false)
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    categories = QueryCategory.objects.filter(chatbot=chatbot)

    # Filter by active status if requested
    active_only = request.GET.get('active_only', 'false').lower() == 'true'
    if active_only:
        categories = categories.filter(is_active=True)

    categories = categories.order_by('display_order', 'name')

    # Get stats
    stats = {
        'total': categories.count(),
        'active': categories.filter(is_active=True).count()
    }

    serializer = QueryCategorySerializer(categories, many=True)

    return Response({
        'results': serializer.data,
        'stats': stats
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_query_category(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/categories/create/ — Create a new query category

    Request Body:
    - name: string (required) - Category name (e.g., 'Billing', 'Technical Support')
    - description: string (optional) - Description to help AI classify
    - keywords: array (optional) - Keywords/phrases indicating this category
    - color: string (optional) - Hex color for analytics display
    - display_order: int (optional) - Display order (default: 0)
    - is_active: boolean (optional) - Whether active (default: true)
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    serializer = QueryCategoryCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Check for duplicate name
    name = serializer.validated_data.get('name')
    if QueryCategory.objects.filter(chatbot=chatbot, name__iexact=name).exists():
        return Response(
            {'error': f"Category '{name}' already exists for this chatbot"},
            status=status.HTTP_400_BAD_REQUEST
        )

    category = QueryCategory.objects.create(
        chatbot=chatbot,
        **serializer.validated_data
    )

    logger.info(
        f"Created query category '{name}' for chatbot {chatbot_id}",
        extra={'chatbot_id': str(chatbot_id), 'category_id': str(category.id)}
    )

    return Response(
        QueryCategorySerializer(category).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_create_categories(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/categories/bulk/ — Bulk create query categories

    Request Body:
    - categories: array of category objects with name, description, keywords, color
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    serializer = QueryCategoryBulkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Get existing category names
    existing_names = set(
        QueryCategory.objects.filter(chatbot=chatbot)
        .values_list('name', flat=True)
    )
    existing_names_lower = {n.lower() for n in existing_names}

    created_categories = []
    skipped = []

    for cat_data in serializer.validated_data['categories']:
        if cat_data['name'].lower() in existing_names_lower:
            skipped.append(cat_data['name'])
            continue

        category = QueryCategory.objects.create(
            chatbot=chatbot,
            **cat_data
        )
        created_categories.append(category)
        existing_names_lower.add(cat_data['name'].lower())

    logger.info(
        f"Bulk created {len(created_categories)} query categories for chatbot {chatbot_id}",
        extra={'chatbot_id': str(chatbot_id), 'count': len(created_categories)}
    )

    return Response({
        'message': f'Successfully created {len(created_categories)} categories',
        'categories': QueryCategorySerializer(created_categories, many=True).data,
        'skipped': skipped
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def query_category_detail(request, category_id):
    """
    GET/PUT/DELETE /categories/{category_id}/ — Manage individual query category
    """
    try:
        category = QueryCategory.objects.select_related('chatbot').get(id=category_id)
    except QueryCategory.DoesNotExist:
        return Response(
            {'error': 'Query category not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, category.chatbot_id)

    if request.method == 'GET':
        return Response(QueryCategorySerializer(category).data)

    elif request.method == 'PUT':
        serializer = QueryCategoryCreateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        # Check for duplicate name if name is being changed
        new_name = serializer.validated_data.get('name')
        if new_name and new_name.lower() != category.name.lower():
            if QueryCategory.objects.filter(
                chatbot=chatbot,
                name__iexact=new_name
            ).exclude(id=category_id).exists():
                return Response(
                    {'error': f"Category '{new_name}' already exists for this chatbot"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        for key, value in serializer.validated_data.items():
            setattr(category, key, value)
        category.save()

        logger.info(f"Updated query category {category_id}")
        return Response(QueryCategorySerializer(category).data)

    elif request.method == 'DELETE':
        category.delete()
        logger.info(f"Deleted query category {category_id}")
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_category(request, category_id):
    """
    POST /categories/{category_id}/toggle/ — Toggle active status of a query category
    """
    try:
        category = QueryCategory.objects.select_related('chatbot').get(id=category_id)
    except QueryCategory.DoesNotExist:
        return Response(
            {'error': 'Query category not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, category.chatbot_id)

    category.is_active = not category.is_active
    category.save(update_fields=['is_active', 'updated_at'])

    logger.info(f"Toggled query category {category_id} to {'active' if category.is_active else 'inactive'}")

    return Response({
        'id': str(category.id),
        'is_active': category.is_active,
        'message': f'Category {"activated" if category.is_active else "deactivated"}'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reorder_categories(request, chatbot_id):
    """
    POST /chatbots/{chatbot_id}/categories/reorder/ — Reorder query categories

    Request Body:
    - order: array of {id, display_order} objects
    """
    # Validate chatbot access
    chatbot = check_chatbot_access(request.user, chatbot_id)

    order_data = request.data.get('order', [])
    if not isinstance(order_data, list):
        return Response(
            {'error': 'Order must be a list'},
            status=status.HTTP_400_BAD_REQUEST
        )

    updated_count = 0
    for item in order_data:
        category_id = item.get('id')
        display_order = item.get('display_order')

        if category_id and display_order is not None:
            try:
                category = QueryCategory.objects.get(
                    id=category_id,
                    chatbot=chatbot
                )
                category.display_order = int(display_order)
                category.save(update_fields=['display_order'])
                updated_count += 1
            except (QueryCategory.DoesNotExist, ValueError):
                continue

    logger.info(f"Reordered {updated_count} query categories for chatbot {chatbot_id}")

    return Response({
        'message': f'Successfully reordered {updated_count} categories',
        'updated_count': updated_count
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([ChatbotThrottle, ChatbotAnonThrottle])
def public_categories(request, api_key):
    """
    GET /chatbot/{api_key}/categories/ — Get active query categories for a chatbot (public)

    This is a public endpoint used by the embedded chatbot backend to get
    categories for query classification.
    """
    try:
        chatbot = Chatbot.objects.get(api_key=api_key, status='active')
    except Chatbot.DoesNotExist:
        return Response(
            {'error': 'Chatbot not found or inactive'},
            status=status.HTTP_404_NOT_FOUND
        )

    categories = QueryCategory.objects.filter(
        chatbot=chatbot,
        is_active=True
    ).order_by('display_order', 'name')

    # Simplified response for embedded backend
    result = []
    for category in categories:
        result.append({
            'id': str(category.id),
            'name': category.name,
            'description': category.description,
            'keywords': category.keywords
        })

    return Response({
        'categories': result,
        'chatbot_name': chatbot.name
    })

