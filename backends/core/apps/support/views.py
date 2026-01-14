"""
Views for FAQ, Feedback, and Help Center APIs
"""
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .models import FAQ, FAQCategory, Feedback, HelpArticle
from .serializers import (
    FAQSerializer, FAQListSerializer, FAQCategorySerializer,
    FeedbackSerializer, FeedbackCreateSerializer,
    HelpArticleSerializer, HelpArticleListSerializer
)
from .services import feedback_notification_service
from apps.core.logging_config import get_logger

logger = get_logger(__name__)


class FAQCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for FAQ categories"""
    queryset = FAQCategory.objects.filter(is_active=True)
    serializer_class = FAQCategorySerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    @action(detail=True, methods=['get'])
    def faqs(self, request, slug=None):
        """Get all FAQs in a category"""
        category = self.get_object()
        faqs = FAQ.objects.filter(category=category, is_active=True)
        serializer = FAQListSerializer(faqs, many=True)
        return Response(serializer.data)


class FAQViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for FAQs"""
    queryset = FAQ.objects.filter(is_active=True).select_related('category')
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'list':
            return FAQListSerializer
        return FAQSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category__slug=category)

        # Filter by featured
        featured = self.request.query_params.get('featured')
        if featured and featured.lower() == 'true':
            queryset = queryset.filter(is_featured=True)

        # Search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(question__icontains=search) |
                Q(answer__icontains=search) |
                Q(tags__icontains=search)
            )

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Increment view count when FAQ is viewed"""
        instance = self.get_object()
        instance.increment_view()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def helpful(self, request, pk=None):
        """Mark FAQ as helpful"""
        faq = self.get_object()
        faq.mark_helpful()
        return Response({'status': 'success', 'helpful_count': faq.helpful_count})

    @action(detail=True, methods=['post'])
    def not_helpful(self, request, pk=None):
        """Mark FAQ as not helpful"""
        faq = self.get_object()
        faq.mark_not_helpful()
        return Response({'status': 'success', 'not_helpful_count': faq.not_helpful_count})

    @action(detail=False, methods=['get'])
    def search(self, request):
        """Search FAQs"""
        query = request.query_params.get('q', '')
        if len(query) < 2:
            return Response({'results': [], 'count': 0})

        faqs = self.get_queryset().filter(
            Q(question__icontains=query) |
            Q(answer__icontains=query) |
            Q(tags__icontains=query)
        )[:20]

        serializer = FAQListSerializer(faqs, many=True)
        return Response({
            'results': serializer.data,
            'count': len(serializer.data),
            'query': query
        })


class FeedbackViewSet(viewsets.ModelViewSet):
    """ViewSet for user feedback"""
    serializer_class = FeedbackSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Users can only see their own feedback"""
        if self.request.user.is_authenticated:
            return Feedback.objects.filter(user=self.request.user)
        return Feedback.objects.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return FeedbackCreateSerializer
        return FeedbackSerializer

    def create(self, request, *args, **kwargs):
        """Create new feedback"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feedback = serializer.save()

        # Send admin notification asynchronously (non-blocking)
        try:
            feedback_notification_service.send_admin_notification(feedback)
        except Exception as e:
            # Log but don't fail the request if notification fails
            logger.warning(
                "Failed to send admin notification for new feedback",
                extra={'feedback_id': str(feedback.id), 'error': str(e)}
            )

        # Return the created feedback with full details
        response_serializer = FeedbackSerializer(feedback)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def my_feedback(self, request):
        """Get current user's feedback submissions"""
        feedback = self.get_queryset().order_by('-created_at')
        serializer = FeedbackSerializer(feedback, many=True)
        return Response(serializer.data)


class HelpArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for help center articles"""
    queryset = HelpArticle.objects.filter(is_active=True).select_related('category')
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_serializer_class(self):
        if self.action == 'list':
            return HelpArticleListSerializer
        return HelpArticleSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category__slug=category)

        # Filter by type
        article_type = self.request.query_params.get('type')
        if article_type:
            queryset = queryset.filter(article_type=article_type)

        # Filter by featured
        featured = self.request.query_params.get('featured')
        if featured and featured.lower() == 'true':
            queryset = queryset.filter(is_featured=True)

        # Search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(summary__icontains=search) |
                Q(content__icontains=search) |
                Q(tags__icontains=search)
            )

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """Increment view count when article is viewed"""
        instance = self.get_object()
        instance.increment_view()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def helpful(self, request, slug=None):
        """Mark article as helpful"""
        article = self.get_object()
        article.helpful_count += 1
        article.save(update_fields=['helpful_count', 'updated_at'])
        return Response({'status': 'success', 'helpful_count': article.helpful_count})

    @action(detail=True, methods=['post'])
    def not_helpful(self, request, slug=None):
        """Mark article as not helpful"""
        article = self.get_object()
        article.not_helpful_count += 1
        article.save(update_fields=['not_helpful_count', 'updated_at'])
        return Response({'status': 'success', 'not_helpful_count': article.not_helpful_count})

    @action(detail=False, methods=['get'])
    def search(self, request):
        """Search help articles"""
        query = request.query_params.get('q', '')
        if len(query) < 2:
            return Response({'results': [], 'count': 0})

        articles = self.get_queryset().filter(
            Q(title__icontains=query) |
            Q(summary__icontains=query) |
            Q(content__icontains=query) |
            Q(tags__icontains=query)
        )[:20]

        serializer = HelpArticleListSerializer(articles, many=True)
        return Response({
            'results': serializer.data,
            'count': len(serializer.data),
            'query': query
        })

    @action(detail=False, methods=['get'])
    def getting_started(self, request):
        """Get getting started articles"""
        articles = self.get_queryset().filter(article_type='getting_started')[:10]
        serializer = HelpArticleListSerializer(articles, many=True)
        return Response(serializer.data)
