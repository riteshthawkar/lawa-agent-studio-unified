from rest_framework import serializers
from .models import Chatbot, ConversationStarter, QueryCategory
from apps.sites.models import Site
from apps.indexing.models import IndexingJob


class ChatbotSerializer(serializers.ModelSerializer):
    """Serializer for Chatbot model - production ready with full validation"""
    websocket_url = serializers.ReadOnlyField(source='get_websocket_url')
    widget_preview_url = serializers.ReadOnlyField()
    is_active = serializers.ReadOnlyField()
    # Expose site_id for backward compatibility (from ForeignKey)
    site_id = serializers.UUIDField(source='site.id', read_only=True)
    site_name = serializers.SerializerMethodField()
    site_domain = serializers.CharField(source='site.domain', read_only=True)

    class Meta:
        model = Chatbot
        fields = (
            'id', 'site_id', 'site_name', 'site_domain', 'name', 'description', 'status',
            'api_key', 'embed_code', 'websocket_url', 'widget_preview_url', 'is_active',
            # AI Behavior Configuration
            'config',
            # Chatbot Personality
            'chatbot_tone', 'response_length',
            # Widget Configuration Fields
            'theme', 'position', 'primary_color', 'text_color', 'auto_open',
            'greeting_message', 'placeholder_text',
            # Advanced Configuration
            'enable_typing_indicator', 'enable_sound_notifications',
            'max_retries', 'reconnect_delay',
            # Language
            'language',
            # Timestamps
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'site_id', 'api_key', 'embed_code', 'websocket_url',
                          'widget_preview_url', 'is_active', 'created_at', 'updated_at')

    def get_site_name(self, obj):
        """Get site name or domain from the related site"""
        if obj.site:
            return obj.site.name or obj.site.domain
        return "Unknown"
    
    def validate_name(self, value):
        """Validate chatbot name"""
        if not value or not value.strip():
            raise serializers.ValidationError("Chatbot name cannot be empty")
        if len(value.strip()) > 255:
            raise serializers.ValidationError("Chatbot name cannot exceed 255 characters")
        return value.strip()
    
    def validate_description(self, value):
        """Validate chatbot description"""
        if value and len(value) > 1000:
            raise serializers.ValidationError("Description cannot exceed 1000 characters")
        return value
    
    def validate_primary_color(self, value):
        """Validate hex color format"""
        if value:
            if not value.startswith('#'):
                raise serializers.ValidationError("Primary color must be in hex format (e.g., #2563eb)")
            if len(value) != 7:
                raise serializers.ValidationError("Primary color must be 7 characters long (e.g., #2563eb)")
            # Validate hex characters
            try:
                int(value[1:], 16)
            except ValueError:
                raise serializers.ValidationError("Primary color contains invalid hex characters")
        return value

    def validate_text_color(self, value):
        """Validate hex color format for text color"""
        if value:
            if not value.startswith('#'):
                raise serializers.ValidationError("Text color must be in hex format (e.g., #ffffff)")
            if len(value) != 7:
                raise serializers.ValidationError("Text color must be 7 characters long (e.g., #ffffff)")
            try:
                int(value[1:], 16)
            except ValueError:
                raise serializers.ValidationError("Text color contains invalid hex characters")
        return value

    def validate_config(self, value):
        """Validate config field structure"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Config must be a dictionary")
        
        # Validate config keys if present
        allowed_keys = ['model', 'temperature', 'max_tokens', 'system_prompt', 'top_p', 'frequency_penalty', 'presence_penalty']
        for key in value.keys():
            if key not in allowed_keys:
                raise serializers.ValidationError(f"Invalid config key: {key}. Allowed keys: {', '.join(allowed_keys)}")
        
        # Validate temperature if present
        if 'temperature' in value:
            temp = value['temperature']
            if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
                raise serializers.ValidationError("Temperature must be a number between 0 and 2")
        
        # Validate max_tokens if present
        if 'max_tokens' in value:
            tokens = value['max_tokens']
            if not isinstance(tokens, int) or tokens < 1 or tokens > 4000:
                raise serializers.ValidationError("Max tokens must be an integer between 1 and 4000")
        
        # Validate system_prompt if present
        if 'system_prompt' in value:
            prompt = value['system_prompt']
            if not isinstance(prompt, str):
                raise serializers.ValidationError("System prompt must be a string")
            if len(prompt) > 2000:
                raise serializers.ValidationError("System prompt cannot exceed 2000 characters")
        
        return value
    
    def validate_greeting_message(self, value):
        """Validate greeting message length"""
        if value and len(value) > 500:
            raise serializers.ValidationError("Greeting message cannot exceed 500 characters")
        return value
    
    def validate_placeholder_text(self, value):
        """Validate placeholder text length"""
        if value and len(value) > 100:
            raise serializers.ValidationError("Placeholder text cannot exceed 100 characters")
        return value


class ChatbotCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating chatbots - simplified for MVP"""

    class Meta:
        model = Chatbot
        fields = (
            'name', 'description',
            # AI Configuration
            'config',
            # Chatbot Personality
            'chatbot_tone', 'response_length',
            # Widget Configuration (optional during creation)
            'theme', 'position', 'primary_color', 'text_color', 'auto_open',
            'greeting_message', 'placeholder_text',
            # Advanced Configuration (optional during creation)
            'enable_typing_indicator', 'enable_sound_notifications',
            'max_retries', 'reconnect_delay',
            # Language
            'language'
        )
    
    def validate_name(self, value):
        """Validate chatbot name"""
        if not value.strip():
            raise serializers.ValidationError("Chatbot name cannot be empty")
        if len(value) > 255:
            raise serializers.ValidationError("Chatbot name cannot exceed 255 characters")
        return value.strip()
    
    def validate_description(self, value):
        """Validate chatbot description"""
        if value and len(value) > 1000:
            raise serializers.ValidationError("Description cannot exceed 1000 characters")
        return value
    
    def validate_primary_color(self, value):
        """Validate hex color format"""
        if value and not value.startswith('#'):
            raise serializers.ValidationError("Primary color must be in hex format (e.g., #2563eb)")
        if value and len(value) != 7:
            raise serializers.ValidationError("Primary color must be 7 characters long (e.g., #2563eb)")
        return value
    
    def validate_greeting_message(self, value):
        """Validate greeting message length"""
        if value and len(value) > 500:
            raise serializers.ValidationError("Greeting message cannot exceed 500 characters")
        return value
    
    def validate_placeholder_text(self, value):
        """Validate placeholder text length"""
        if value and len(value) > 100:
            raise serializers.ValidationError("Placeholder text cannot exceed 100 characters")
        return value


class IndexInfoSerializer(serializers.Serializer):
    """Serializer for chatbot index information response"""
    site = serializers.DictField()
    indexing_info = serializers.DictField()
    chatbot_config = serializers.DictField()
    api_endpoints = serializers.DictField()


class ChatbotIndexInfoSerializer(serializers.Serializer):
    """Serializer for chatbot index info request"""
    domain = serializers.URLField(required=True)
    api_key = serializers.CharField(required=True)


class ConversationStarterSerializer(serializers.ModelSerializer):
    """Serializer for ConversationStarter model"""

    class Meta:
        model = ConversationStarter
        fields = (
            'id', 'chatbot_id', 'question', 'category', 'is_active',
            'display_order', 'click_count', 'is_auto_generated',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'click_count', 'is_auto_generated', 'created_at', 'updated_at')

    def validate_question(self, value):
        """Validate question text"""
        if not value or not value.strip():
            raise serializers.ValidationError("Question cannot be empty")
        if len(value) > 500:
            raise serializers.ValidationError("Question cannot exceed 500 characters")
        return value.strip()

    def validate_category(self, value):
        """Validate category"""
        if value and len(value) > 100:
            raise serializers.ValidationError("Category cannot exceed 100 characters")
        return value.strip() if value else ''


class ConversationStarterCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating conversation starters"""

    class Meta:
        model = ConversationStarter
        fields = ('question', 'category', 'is_active', 'display_order')

    def validate_question(self, value):
        """Validate question text"""
        if not value or not value.strip():
            raise serializers.ValidationError("Question cannot be empty")
        if len(value) > 500:
            raise serializers.ValidationError("Question cannot exceed 500 characters")
        return value.strip()

    def validate_category(self, value):
        """Validate category"""
        if value and len(value) > 100:
            raise serializers.ValidationError("Category cannot exceed 100 characters")
        return value.strip() if value else ''


class ConversationStarterBulkSerializer(serializers.Serializer):
    """Serializer for bulk operations on conversation starters"""
    starters = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=20,
        help_text="List of starter objects with question, category, display_order"
    )

    def validate_starters(self, value):
        """Validate the list of starters"""
        validated = []
        for i, starter in enumerate(value):
            question = starter.get('question', '')
            if not question or not question.strip():
                raise serializers.ValidationError(f"Starter {i+1}: Question cannot be empty")
            if len(question) > 500:
                raise serializers.ValidationError(f"Starter {i+1}: Question cannot exceed 500 characters")

            category = starter.get('category', '')
            if category and len(category) > 100:
                raise serializers.ValidationError(f"Starter {i+1}: Category cannot exceed 100 characters")

            validated.append({
                'question': question.strip(),
                'category': category.strip() if category else '',
                'display_order': starter.get('display_order', i),
                'is_active': starter.get('is_active', True)
            })
        return validated


# ============================================================================
# Query Category Serializers
# ============================================================================

class QueryCategorySerializer(serializers.ModelSerializer):
    """Serializer for QueryCategory model - full read/write"""

    class Meta:
        model = QueryCategory
        fields = (
            'id', 'chatbot_id', 'name', 'description', 'keywords',
            'color', 'is_active', 'display_order',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate_name(self, value):
        """Validate category name"""
        if not value or not value.strip():
            raise serializers.ValidationError("Category name cannot be empty")
        if len(value) > 100:
            raise serializers.ValidationError("Category name cannot exceed 100 characters")
        return value.strip()

    def validate_description(self, value):
        """Validate description"""
        if value and len(value) > 1000:
            raise serializers.ValidationError("Description cannot exceed 1000 characters")
        return value.strip() if value else ''

    def validate_keywords(self, value):
        """Validate keywords list"""
        if not isinstance(value, list):
            raise serializers.ValidationError("Keywords must be a list")
        # Validate each keyword
        validated = []
        for keyword in value:
            if not isinstance(keyword, str):
                raise serializers.ValidationError("Each keyword must be a string")
            keyword = keyword.strip()
            if keyword and len(keyword) <= 100:
                validated.append(keyword)
        return validated

    def validate_color(self, value):
        """Validate hex color format"""
        if value:
            if not value.startswith('#'):
                raise serializers.ValidationError("Color must be in hex format (e.g., #6366f1)")
            if len(value) != 7:
                raise serializers.ValidationError("Color must be 7 characters long (e.g., #6366f1)")
            try:
                int(value[1:], 16)
            except ValueError:
                raise serializers.ValidationError("Color contains invalid hex characters")
        return value


class QueryCategoryCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating query categories"""

    class Meta:
        model = QueryCategory
        fields = ('name', 'description', 'keywords', 'color', 'is_active', 'display_order')

    def validate_name(self, value):
        """Validate category name"""
        if not value or not value.strip():
            raise serializers.ValidationError("Category name cannot be empty")
        if len(value) > 100:
            raise serializers.ValidationError("Category name cannot exceed 100 characters")
        return value.strip()

    def validate_keywords(self, value):
        """Validate keywords list"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Keywords must be a list")
        validated = []
        for keyword in value:
            if isinstance(keyword, str):
                keyword = keyword.strip()
                if keyword and len(keyword) <= 100:
                    validated.append(keyword)
        return validated

    def validate_color(self, value):
        """Validate hex color format"""
        if value:
            if not value.startswith('#'):
                raise serializers.ValidationError("Color must be in hex format (e.g., #6366f1)")
            if len(value) != 7:
                raise serializers.ValidationError("Color must be 7 characters long")
            try:
                int(value[1:], 16)
            except ValueError:
                raise serializers.ValidationError("Color contains invalid hex characters")
        return value or '#6366f1'


class QueryCategoryBulkSerializer(serializers.Serializer):
    """Serializer for bulk operations on query categories"""
    categories = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        max_length=50,
        help_text="List of category objects with name, description, keywords, color"
    )

    def validate_categories(self, value):
        """Validate the list of categories"""
        validated = []
        seen_names = set()

        for i, category in enumerate(value):
            name = category.get('name', '')
            if not name or not name.strip():
                raise serializers.ValidationError(f"Category {i+1}: Name cannot be empty")
            name = name.strip()
            if len(name) > 100:
                raise serializers.ValidationError(f"Category {i+1}: Name cannot exceed 100 characters")

            # Check for duplicates in this batch
            if name.lower() in seen_names:
                raise serializers.ValidationError(f"Category {i+1}: Duplicate category name '{name}'")
            seen_names.add(name.lower())

            description = category.get('description', '')
            if description and len(description) > 1000:
                raise serializers.ValidationError(f"Category {i+1}: Description cannot exceed 1000 characters")

            keywords = category.get('keywords', [])
            if not isinstance(keywords, list):
                keywords = []
            keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]

            color = category.get('color', '#6366f1')
            if color and not color.startswith('#'):
                color = '#6366f1'

            validated.append({
                'name': name,
                'description': description.strip() if description else '',
                'keywords': keywords,
                'color': color,
                'display_order': category.get('display_order', i),
                'is_active': category.get('is_active', True)
            })
        return validated


class QueryCategoryListSerializer(serializers.Serializer):
    """Lightweight serializer for listing categories (used by embedded chatbot)"""
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    keywords = serializers.ListField(child=serializers.CharField())
