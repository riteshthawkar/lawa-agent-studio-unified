"""
Serializers for FAQ, Feedback, and Help Center
"""
from rest_framework import serializers
from .models import FAQ, FAQCategory, Feedback, HelpArticle


class FAQCategorySerializer(serializers.ModelSerializer):
    """Serializer for FAQ categories"""
    faq_count = serializers.SerializerMethodField()

    class Meta:
        model = FAQCategory
        fields = ['id', 'name', 'slug', 'description', 'icon', 'order', 'faq_count']

    def get_faq_count(self, obj):
        return obj.faqs.filter(is_active=True).count()


class FAQSerializer(serializers.ModelSerializer):
    """Serializer for FAQ items"""
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    category_slug = serializers.CharField(source='category.slug', read_only=True, default=None)

    class Meta:
        model = FAQ
        fields = [
            'id', 'question', 'answer', 'category', 'category_name', 'category_slug',
            'is_featured', 'helpful_count', 'not_helpful_count', 'view_count', 'tags',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['helpful_count', 'not_helpful_count', 'view_count']


class FAQListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for FAQ listings"""
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = FAQ
        fields = ['id', 'question', 'answer', 'category_name', 'is_featured', 'tags']


class FeedbackCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating feedback"""

    class Meta:
        model = Feedback
        fields = [
            'feedback_type', 'subject', 'message',
            'page_url', 'user_agent', 'screen_resolution',
            'steps_to_reproduce', 'expected_behavior', 'actual_behavior'
        ]

    def validate_message(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError("Feedback message must be at least 10 characters")
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['user'] = request.user
            # Get org_id from user's membership
            membership = request.user.memberships.filter(
                organization__status='active',
                is_active=True
            ).first()
            if membership:
                validated_data['org_id'] = membership.organization_id
        return super().create(validated_data)


class FeedbackSerializer(serializers.ModelSerializer):
    """Full feedback serializer for viewing"""
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Feedback
        fields = [
            'id', 'feedback_type', 'feedback_type_display', 'subject', 'message',
            'status', 'status_display', 'priority', 'created_at', 'updated_at',
            'page_url', 'steps_to_reproduce', 'expected_behavior', 'actual_behavior'
        ]
        read_only_fields = ['status', 'priority']


class HelpArticleListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for article listings"""
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    article_type_display = serializers.CharField(source='get_article_type_display', read_only=True)

    class Meta:
        model = HelpArticle
        fields = [
            'id', 'title', 'slug', 'summary', 'icon',
            'article_type', 'article_type_display',
            'category', 'category_name', 'is_featured', 'tags'
        ]


class HelpArticleSerializer(serializers.ModelSerializer):
    """Full serializer for article detail"""
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    article_type_display = serializers.CharField(source='get_article_type_display', read_only=True)
    related_articles = HelpArticleListSerializer(many=True, read_only=True)

    class Meta:
        model = HelpArticle
        fields = [
            'id', 'title', 'slug', 'summary', 'content', 'icon',
            'article_type', 'article_type_display',
            'category', 'category_name', 'is_featured',
            'view_count', 'helpful_count', 'not_helpful_count',
            'related_articles', 'tags', 'created_at', 'updated_at'
        ]
        read_only_fields = ['view_count', 'helpful_count', 'not_helpful_count']
