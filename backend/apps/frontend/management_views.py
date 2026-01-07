"""
Management views for creating and updating resources from frontend
"""
from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
import logging

from apps.organizations.models import Organization, Membership
from apps.sites.models import Site, ExcludedURLPattern
from apps.indexing.models import IndexingJob
from apps.chatbot.models import Chatbot
from apps.indexing.services import IndexingService
from apps.sites.serializers import SiteCreateSerializer
from apps.usage.services import QuotaService
from .serializers import (
    ChatbotCreateSerializer
)
from apps.indexing.serializers import IndexingJobCreateSerializer


logger = logging.getLogger(__name__)


class FrontendThrottle(UserRateThrottle):
    scope = 'frontend'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def create_site(request):
    """
    POST /v1/frontend/sites/create/ — Create a new site
    
    Creates a new site for indexing with verification setup.
    """
    logger.info(f"Create site request from user: {getattr(request.user, 'id', 'anonymous')}")
    
    try:
        # Get organization context
        org_id = getattr(request, 'org_id', None)

        # Get user's organization for plan tier
        membership = Membership.objects.filter(user=request.user).first()
        plan_tier = 'trial'  # Default
        if membership and membership.organization:
            plan_tier = getattr(membership.organization, 'plan_tier', 'trial')

        # Check site quota
        if org_id:
            allowed, message = QuotaService.check_site_limit(str(org_id))
            if not allowed:
                return Response(
                    {'error': message},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Validate and create site
        serializer = SiteCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            # Auto-verify sites (verification requirement disabled for MVP)
            
            site = serializer.save(org_id=org_id)
            # Note: status and verified_at are already set by the serializer
            
            # MVP: Automatically start indexing after site creation
            try:
                from urllib.parse import urlparse

                logger.info(f"Starting indexing for site {site.id} with domain {site.domain}")
                indexing_service = IndexingService()
                logger.info(f"Indexing service initialized with base URL: {indexing_service.base_url}")

                parsed_domain = urlparse(site.domain)
                allowed_domains = []
                if parsed_domain.netloc:
                    allowed_domains.append(parsed_domain.netloc)

                # Use site's indexing configuration
                job_params = {
                    'url': site.domain,
                    'max_pages': site.max_pages,
                    'allowed_domains': allowed_domains,
                    'use_namespaces': True,
                    'namespace_prefix': 'website_domain',
                    'streaming_mode': True,
                    'scrape_all_subdomains': site.scrape_all_subdomains or site.include_subdomains,
                    'custom_config': {
                        'crawler': {
                            'default_delay': site.crawl_delay,
                            'headless': True,
                            'stealth': True,
                        },
                        'pdf': {
                            'enabled': site.enable_pdf_processing,
                            'ocr_enabled': False,
                        },
                        'dynamic_content': {
                            'infinite_scroll_enabled': site.enable_dynamic_content,
                            'lazy_load_images': True,
                        }
                    }
                }

                logger.info(f"Job params: {job_params}")

                # Create indexing job
                indexing_job = indexing_service.create_indexing_job(
                    site=site,
                    params=job_params,
                    user_id=getattr(request.user, 'id', 'anonymous'),
                    callback_url=None  # MVP: Skip callback for now
                )
                
                logger.info(f"Created site {site.id} and started indexing job {indexing_job.id}")

                return Response({
                    'id': str(site.id),
                    'domain': site.domain,
                    'status': site.status,
                    'message': 'Site created successfully and indexing started.',
                    'indexing_job': {
                        'id': str(indexing_job.id),
                        'task_id': indexing_job.task_id,
                        'status': indexing_job.status
                    }
                }, status=status.HTTP_201_CREATED)

            except Exception as indexing_error:
                # Log indexing error but don't fail site creation
                logger.error(f"Failed to start indexing for site {site.id}: {str(indexing_error)}", exc_info=True)

            return Response({
                'id': str(site.id),
                'domain': site.domain,
                'status': site.status,
                'message': 'Site created successfully but indexing failed to start.'
            }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error creating site: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def create_indexing_job(request, site_id):
    """
    POST /v1/frontend/sites/{site_id}/indexing-jobs/create/ — Create indexing job - simplified for MVP
    
    Creates a new indexing job for a specific site.
    """
    logger.info(f"Create indexing job request from user: {getattr(request.user, 'id', 'anonymous')} for site: {site_id}")
    
    try:
        # Get site - Filtered by Organization
        org_id = getattr(request, 'org_id', None)
        lookup_kwargs = {'id': site_id}
        if org_id:
            lookup_kwargs['org_id'] = org_id
            
        site = get_object_or_404(Site, **lookup_kwargs)
        
        # Check if site is inactive
        if site.status == 'inactive':
            return Response(
                {'error': 'Site is inactive and cannot be indexed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check indexing job quota
        if org_id:
            membership = Membership.objects.filter(user=request.user).first()
            plan_tier = 'trial'
            if membership and membership.organization:
                plan_tier = getattr(membership.organization, 'plan_tier', 'trial')

            allowed, message = QuotaService.check_indexing_job_quota(str(org_id), plan_tier)
            if not allowed:
                return Response(
                    {'error': message},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Validate request data
        serializer = IndexingJobCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Inject active excluded subdomains and patterns from DB
        params = serializer.validated_data
        
        # 1. Excluded Patterns (regex, prefix, etc.)
        excluded_patterns_qs = ExcludedURLPattern.objects.filter(site_id=site.id, is_active=True)
        if excluded_patterns_qs.exists():
            patterns_list = []
            for ep in excluded_patterns_qs:
                patterns_list.append({
                    'pattern': ep.pattern,
                    'type': ep.pattern_type
                })
            params['excluded_patterns'] = patterns_list
            logger.info(f"Injected {len(patterns_list)} exclusion patterns for site {site_id}")

        # Create indexing job
        indexing_service = IndexingService()
        
        with transaction.atomic():
            job = indexing_service.create_indexing_job(
                site=site,
                params=params,
                user_id=getattr(request.user, 'id', 'anonymous')  # Pass UUID directly, not as string
            )
            
            logger.info(f"Created indexing job {job.id} for site {site_id}")
            
            return Response({
                'id': str(job.id),
                'external_job_id': job.external_job_id,
                'task_id': job.task_id,
                'status': job.status,
                'url': job.url,
                'max_pages': job.max_pages,
                'message': 'Indexing job created successfully'
            }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error creating indexing job: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def create_chatbot(request, site_id):
    """
    POST /v1/frontend/sites/{site_id}/chatbots/create/ — Create chatbot - simplified for MVP
    
    Creates a new chatbot for a specific site.
    """
    logger.info(f"Create chatbot request from user: {getattr(request.user, 'id', 'anonymous')} for site: {site_id}")
    
    try:
        # Get site - Filtered by Organization
        org_id = getattr(request, 'org_id', None)
        lookup_kwargs = {'id': site_id}
        if org_id:
            lookup_kwargs['org_id'] = org_id

        site = get_object_or_404(Site, **lookup_kwargs)
        
        # Allow chatbot creation for active sites OR sites with completed indexing
        if site.status == 'inactive':
            return Response(
                {'error': 'Site must be active or have completed indexing before creating chatbot'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # For non-active sites, verify they have at least one completed indexing job
        if site.status != 'active':
            has_completed_indexing = IndexingJob.objects.filter(
                site_id=site.id,
                status='completed',
                documents_indexed__gt=0
            ).exists()
            
            if not has_completed_indexing:
                return Response(
                    {'error': 'Site must have at least one completed indexing job before creating chatbot'},
                    status=status.HTTP_400_BAD_REQUEST
                )


        # Check chatbot quota
        if org_id:
            membership = Membership.objects.filter(user=request.user).first()
            plan_tier = 'trial'
            if membership and membership.organization:
                plan_tier = getattr(membership.organization, 'plan_tier', 'trial')

            allowed, message = QuotaService.check_chatbot_limit(str(org_id))
            if not allowed:
                return Response(
                    {'error': message},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Validate request data
        serializer = ChatbotCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Create chatbot
        with transaction.atomic():
            chatbot = serializer.save(
                site_id=site.id,
                status='active'
            )
            
            logger.info(f"Created chatbot {chatbot.id} for site {site_id}")
            
            return Response({
                'id': str(chatbot.id),
                'name': chatbot.name,
                'description': chatbot.description,
                'status': chatbot.status,
                'api_key': chatbot.api_key,
                'embed_code': chatbot.embed_code,
                'websocket_url': chatbot.get_websocket_url(),
                'widget_preview_url': chatbot.widget_preview_url,
                'site_id': str(chatbot.site_id),
                'is_active': chatbot.is_active,
                'created_at': chatbot.created_at.isoformat(),
                'message': 'Chatbot created successfully'
            }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error creating chatbot: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def update_site(request, site_id):
    """
    PUT /v1/frontend/sites/{site_id}/ — Update site - simplified for MVP
    
    Updates site configuration and settings.
    """
    logger.info(f"Update site request from user: {getattr(request.user, 'id', 'anonymous')} for site: {site_id}")
    
    try:
        # Get site - Filtered by Organization
        org_id = getattr(request, 'org_id', None)
        lookup_kwargs = {'id': site_id}
        if org_id:
            lookup_kwargs['org_id'] = org_id
            
        site = get_object_or_404(Site, **lookup_kwargs)
        
        # Update site - simplified for MVP (only status field)
        allowed_fields = ['status']
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        
        if not update_data:
            return Response(
                {'error': 'No valid fields to update'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            for field, value in update_data.items():
                setattr(site, field, value)
            site.save()
            
            logger.info(f"Updated site {site_id}")
            
            return Response({
                'id': str(site.id),
                'domain': site.domain,
                'status': site.status,
                'message': 'Site updated successfully'
            })
        
    except Exception as e:
        logger.error(f"Error updating site: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def get_or_update_chatbot(request, chatbot_id):
    """
    GET /v1/frontend/chatbots/{chatbot_id}/ — Get single chatbot details
    PUT/PATCH /v1/frontend/chatbots/{chatbot_id}/ — Update chatbot
    
    Handles both getting and updating chatbot configuration including AI config.
    """
    logger.info(f"Chatbot request ({request.method}) from user: {getattr(request.user, 'id', 'anonymous')} for chatbot: {chatbot_id}")
    
    try:
        # Get chatbot - Filtered by Organization
        org_id = getattr(request, 'org_id', None)
        chatbot_qs = Chatbot.objects.all()
        if org_id:
            # Chatbot.site_id is UUIDField, not ForeignKey
            org_site_ids = Site.objects.filter(org_id=org_id).values_list('id', flat=True)
            chatbot_qs = chatbot_qs.filter(site_id__in=org_site_ids)
            
        chatbot = get_object_or_404(chatbot_qs, id=chatbot_id)
        
        # Use ChatbotSerializer for consistent response format
        from apps.chatbot.serializers import ChatbotSerializer
        
        # Handle GET request
        if request.method == 'GET':
            serializer = ChatbotSerializer(chatbot)
            return Response(serializer.data)
        
        # Handle PUT/PATCH requests
        elif request.method in ['PUT', 'PATCH']:
            # Partial update for PATCH, full update for PUT
            partial = request.method == 'PATCH'
            serializer = ChatbotSerializer(chatbot, data=request.data, partial=partial)
            
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            with transaction.atomic():
                # Save the updated chatbot
                updated_chatbot = serializer.save()
                
                # If config or widget settings changed, regenerate embed code
                embed_code_changed = any(key in request.data for key in [
                    'config', 'primary_color', 'text_color', 'theme', 'position',
                    'greeting_message', 'placeholder_text', 'auto_open'
                ])
                
                if embed_code_changed:
                    updated_chatbot.regenerate_embed_code()
                
                logger.info(f"Updated chatbot {chatbot_id}")
                
                # Return updated chatbot data
                response_serializer = ChatbotSerializer(updated_chatbot)
                return Response({
                    **response_serializer.data,
                    'message': 'Chatbot updated successfully'
                })
        
    except Exception as e:
        logger.error(f"Error processing chatbot request: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def delete_site(request, site_id):
    """
    DELETE /v1/frontend/sites/{site_id}/ — Delete site - simplified for MVP
    
    Deletes a site and all associated data.
    """
    logger.info(f"Delete site request from user: {getattr(request.user, 'id', 'anonymous')} for site: {site_id}")
    
    try:
        # Get site - Filtered by Organization
        org_id = getattr(request, 'org_id', None)
        lookup_kwargs = {'id': site_id}
        if org_id:
            lookup_kwargs['org_id'] = org_id
            
        site = get_object_or_404(Site, **lookup_kwargs)
        
        with transaction.atomic():
            # Delete associated data (using site_id UUID field, not ForeignKey)
            from apps.indexing.models import IndexingJob
            from apps.chatbot.models import Chatbot
            
            IndexingJob.objects.filter(site_id=site_id).delete()
            Chatbot.objects.filter(site_id=site_id).delete()
            site.delete()
            
            logger.info(f"Deleted site {site_id}")
            
            return Response({
                'message': 'Site deleted successfully'
            })
        
    except Exception as e:
        logger.error(f"Error deleting site: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([FrontendThrottle])
def delete_chatbot(request, chatbot_id):
    """
    DELETE /v1/frontend/chatbots/{chatbot_id}/ — Delete chatbot - simplified for MVP
    
    Deletes a chatbot and all associated data.
    """
    logger.info(f"Delete chatbot request from user: {getattr(request.user, 'id', 'anonymous')} for chatbot: {chatbot_id}")
    
    try:
        # Get chatbot - Filtered by Organization
        org_id = getattr(request, 'org_id', None)

        chatbot_qs = Chatbot.objects.all()
        if org_id:
            # Chatbot.site_id is UUIDField, not ForeignKey
            org_site_ids = Site.objects.filter(org_id=org_id).values_list('id', flat=True)
            chatbot_qs = chatbot_qs.filter(site_id__in=org_site_ids)
            
        chatbot = get_object_or_404(chatbot_qs, id=chatbot_id)
        
        with transaction.atomic():
            # Delete associated chat sessions
            chatbot.chat_sessions.all().delete()
            chatbot.delete()
            
            logger.info(f"Deleted chatbot {chatbot_id}")
            
            return Response({
                'message': 'Chatbot deleted successfully'
            })
        
    except Exception as e:
        logger.error(f"Error deleting chatbot: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
