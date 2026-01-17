from rest_framework import serializers
from .models import ChatSession, ChatMessage, ChatFeedback


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serializer for ChatMessage model"""
    
    class Meta:
        model = ChatMessage
        fields = (
            'id', 'session', 'role', 'content', 'tokens_in',
            'tokens_out', 'citations', 'latency_ms', 'feedback', 'created_at'
        )
        read_only_fields = ('id', 'created_at')


class ChatSessionSerializer(serializers.ModelSerializer):
    """Serializer for ChatSession model"""
    messages = ChatMessageSerializer(many=True, read_only=True)
    feedback = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = (
            'id', 'org_id', 'chatbot_id', 'site_id', 'user_id',
            'session_key', 'meta', 'created_at', 'closed_at',
            'messages', 'feedback'
        )
        read_only_fields = ('id', 'org_id', 'session_key', 'created_at', 'closed_at')

    def create(self, validated_data):
        """Create session with organization context"""
        request = self.context.get('request')
        if request and hasattr(request, 'org_id'):
            validated_data['org_id'] = request.org_id
        return super().create(validated_data)

    def get_feedback(self, obj):
        """Aggregate feedback from messages for the session"""
        # Efficiently check for any likes or dislikes
        # Note: In a real high-volume app, we might want to cache this on the model
        has_like = obj.messages.filter(feedback='like').exists()
        if has_like:
            return 'like'
            
        has_dislike = obj.messages.filter(feedback='dislike').exists()
        if has_dislike:
            return 'dislike'
            
        return 'no_feedback'


class ChatFeedbackSerializer(serializers.ModelSerializer):
    """Serializer for ChatFeedback model"""
    
    class Meta:
        model = ChatFeedback
        fields = (
            'id', 'message', 'feedback_type', 'user_id',
            'ip_address', 'user_agent', 'created_at'
        )
        read_only_fields = ('id', 'user_id', 'ip_address', 'user_agent', 'created_at')
    
    def create(self, validated_data):
        """Create feedback with request context"""
        request = self.context.get('request')
        if request:
            # Set user_id if authenticated
            if hasattr(request, 'user') and request.user.is_authenticated:
                validated_data['user_id'] = request.user.id
            
            # Set IP address and user agent
            validated_data['ip_address'] = self.get_client_ip(request)
            validated_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')
        
        return super().create(validated_data)
    
    def get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class FeedbackUpdateSerializer(serializers.Serializer):
    """Serializer for updating feedback on a message"""
    feedback_type = serializers.ChoiceField(choices=['like', 'dislike'])
    feedback_type = serializers.ChoiceField(choices=['like', 'dislike'])
    
    def validate_feedback_type(self, value):
        """Validate feedback type"""
        if value not in ['like', 'dislike']:
            raise serializers.ValidationError("Feedback type must be 'like' or 'dislike'")
        return value


class MessageFeedbackSerializer(serializers.ModelSerializer):
    """Serializer for message with feedback information"""
    feedbacks = ChatFeedbackSerializer(many=True, read_only=True)
    feedback_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatMessage
        fields = (
            'id', 'session', 'role', 'content', 'tokens_in',
            'tokens_out', 'citations', 'latency_ms', 'feedback',
            'feedbacks', 'feedback_count', 'created_at'
        )
        read_only_fields = ('id', 'created_at')
    
    def get_feedback_count(self, obj):
        """Get feedback count for the message"""
        return {
            'like': obj.feedbacks.filter(feedback_type='like').count(),
            'dislike': obj.feedbacks.filter(feedback_type='dislike').count(),
            'total': obj.feedbacks.count()
        }
