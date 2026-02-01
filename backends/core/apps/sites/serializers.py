from rest_framework import serializers
from django.conf import settings
from django.utils import timezone
from .models import Site, ExcludedURLPattern
import re


class SiteSerializer(serializers.ModelSerializer):
    """Serializer for Site model with full indexing configuration"""
    namespace = serializers.ReadOnlyField(source='get_namespace')
    excluded_patterns_count = serializers.SerializerMethodField()
    active_excluded_patterns_count = serializers.SerializerMethodField()
    is_verified = serializers.ReadOnlyField()

    class Meta:
        model = Site
        fields = (
            'id', 'name', 'domain', 'status', 'namespace', 'last_indexed_at',
            'created_at', 'indexed_pages_count', 'total_documents',
            'verification_mode', 'verification_method', 'verified_at', 'is_verified',
            'max_pages', 'crawl_delay', 'respect_robots', 'include_subdomains',
            'scrape_all_subdomains', 'enable_javascript', 'enable_pdf_processing',
            'enable_dynamic_content', 'indexing_config',
            'excluded_patterns_count', 'active_excluded_patterns_count'
        )
        read_only_fields = ('id', 'created_at', 'last_indexed_at', 'indexed_pages_count', 'total_documents')
    
    def get_excluded_patterns_count(self, obj):
        """Return total count of excluded URL patterns for this site"""
        return ExcludedURLPattern.objects.filter(site_id=obj.id).count()
    
    def get_active_excluded_patterns_count(self, obj):
        """Return count of active excluded URL patterns for this site"""
        return ExcludedURLPattern.objects.filter(site_id=obj.id, is_active=True).count()


class SiteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating sites with indexing configuration"""
    public_content_acknowledged = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Site
        fields = (
            'name', 'domain', 'max_pages', 'crawl_delay', 'respect_robots',
            'include_subdomains', 'scrape_all_subdomains', 'enable_javascript',
            'enable_pdf_processing', 'enable_dynamic_content', 'indexing_config',
            'verification_mode', 'verification_method', 'public_content_acknowledged'
        )
        extra_kwargs = {
            'max_pages': {'min_value': 1}
        }

    def validate_domain(self, value):
        """Validate domain format"""
        if not value or not value.strip():
            raise serializers.ValidationError("Domain cannot be empty")
            
        # Ensure domain has protocol if not provided
        if not value.startswith(('http://', 'https://')):
            value = f'https://{value}'
            
        # Basic domain/URL validation
        url_regex = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ipv4
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            
        if not url_regex.match(value):
            raise serializers.ValidationError("Invalid domain format")
            
        return value

    def validate_max_pages(self, value):
        """Validate max_pages"""
        if value < 1:
            raise serializers.ValidationError("Maximum pages must be at least 1")
        if value > 10000:
            raise serializers.ValidationError("Maximum pages cannot exceed 10000")
        return value

    def validate_crawl_delay(self, value):
        """Validate crawl_delay"""
        if value < 0:
            raise serializers.ValidationError("Crawl delay cannot be negative")
        if value > 30:
            raise serializers.ValidationError("Crawl delay cannot exceed 30 seconds")
        return value

    def create(self, validated_data):
        """Create site with indexing configuration"""
        public_ack = validated_data.pop('public_content_acknowledged', False)
        verification_mode = validated_data.get('verification_mode') or getattr(
            settings, 'SITE_VERIFICATION_DEFAULT_MODE', 'required'
        )
        validated_data['verification_mode'] = verification_mode
        
        # Ensure verification_method has a default
        if 'verification_method' not in validated_data:
            validated_data['verification_method'] = 'dns'

        if verification_mode == 'public':
            require_ack = getattr(settings, 'SITE_VERIFICATION_REQUIRE_PUBLIC_ACK', True)
            if require_ack and not public_ack:
                raise serializers.ValidationError({
                    'public_content_acknowledged': 'Acknowledgment is required for public mode.'
                })
            validated_data['public_acknowledged_at'] = timezone.now()
            if not getattr(settings, 'SITE_PUBLIC_ALLOW_SUBDOMAINS', False):
                validated_data['include_subdomains'] = False
                validated_data['scrape_all_subdomains'] = False
            if not getattr(settings, 'SITE_PUBLIC_ALLOW_DYNAMIC_CONTENT', False):
                validated_data['enable_dynamic_content'] = False
            validated_data['respect_robots'] = True

        # Set status based on verification policy
        if getattr(settings, 'SITE_VERIFICATION_ENABLED', True) and verification_mode == 'required':
            validated_data['status'] = 'inactive'
        else:
            validated_data['status'] = 'active'
        return super().create(validated_data)


class SiteUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating site settings"""
    public_content_acknowledged = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Site
        fields = (
            'status', 'max_pages', 'crawl_delay', 'respect_robots',
            'include_subdomains', 'scrape_all_subdomains', 'enable_javascript',
            'enable_pdf_processing', 'enable_dynamic_content', 'indexing_config',
            'verification_mode', 'verification_method', 'public_content_acknowledged'
        )

    def validate(self, attrs):
        verification_mode = attrs.get('verification_mode')
        public_ack = attrs.pop('public_content_acknowledged', False)

        if verification_mode == 'public':
            require_ack = getattr(settings, 'SITE_VERIFICATION_REQUIRE_PUBLIC_ACK', True)
            if require_ack and not public_ack:
                raise serializers.ValidationError({
                    'public_content_acknowledged': 'Acknowledgment is required for public mode.'
                })
            attrs['public_acknowledged_at'] = timezone.now()
            if not getattr(settings, 'SITE_PUBLIC_ALLOW_SUBDOMAINS', False):
                attrs['include_subdomains'] = False
                attrs['scrape_all_subdomains'] = False
            if not getattr(settings, 'SITE_PUBLIC_ALLOW_DYNAMIC_CONTENT', False):
                attrs['enable_dynamic_content'] = False
            attrs['respect_robots'] = True

        return attrs

    def update(self, instance, validated_data):
        verification_mode = validated_data.get('verification_mode')
        if verification_mode == 'required' and getattr(settings, 'SITE_VERIFICATION_ENABLED', True):
            if not instance.is_verified:
                validated_data.setdefault('status', 'inactive')
        elif verification_mode == 'public':
            validated_data.setdefault('status', 'active')
        return super().update(instance, validated_data)

    def validate_max_pages(self, value):
        """Validate max_pages"""
        if value < 1:
            raise serializers.ValidationError("Maximum pages must be at least 1")
        if value > 10000:
            raise serializers.ValidationError("Maximum pages cannot exceed 10000")
        return value

    def validate_crawl_delay(self, value):
        """Validate crawl_delay"""
        if value < 0:
            raise serializers.ValidationError("Crawl delay cannot be negative")
        if value > 30:
            raise serializers.ValidationError("Crawl delay cannot exceed 30 seconds")
        return value


class SiteVerificationSerializer(serializers.Serializer):
    """Serializer for site verification requests"""
    verification_method = serializers.ChoiceField(
        choices=Site.VERIFICATION_METHOD_CHOICES,
        required=False
    )

    def validate_verification_method(self, value):
        if value not in dict(Site.VERIFICATION_METHOD_CHOICES):
            raise serializers.ValidationError("Invalid verification method")
        return value


# Excluded URL Pattern serializers

class ExcludedURLPatternSerializer(serializers.ModelSerializer):
    """Serializer for ExcludedURLPattern model"""
    pattern_type_display = serializers.CharField(source='get_pattern_type_display', read_only=True)

    class Meta:
        model = ExcludedURLPattern
        fields = (
            'id', 'site_id', 'pattern', 'pattern_type', 'pattern_type_display',
            'description', 'is_active', 'urls_matched',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'site_id', 'urls_matched', 'created_at', 'updated_at')


class ExcludedURLPatternListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing excluded patterns"""
    pattern_type_display = serializers.CharField(source='get_pattern_type_display', read_only=True)

    class Meta:
        model = ExcludedURLPattern
        fields = (
            'id', 'pattern', 'pattern_type', 'pattern_type_display',
            'description', 'is_active', 'urls_matched'
        )


class ExcludedURLPatternCreateSerializer(serializers.Serializer):
    """Serializer for creating excluded URL patterns"""
    pattern = serializers.CharField(max_length=2000, help_text="URL pattern to exclude")
    pattern_type = serializers.ChoiceField(
        choices=ExcludedURLPattern.PATTERN_TYPE_CHOICES,
        default='prefix',
        help_text="How to match the pattern"
    )
    description = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Description or reason for exclusion"
    )
    is_active = serializers.BooleanField(default=True)

    def validate_pattern(self, value):
        """Validate pattern format"""
        if not value or not value.strip():
            raise serializers.ValidationError("Pattern cannot be empty")
        return value.strip()

    def validate(self, attrs):
        """Validate the pattern based on type"""
        pattern_type = attrs.get('pattern_type', 'prefix')
        pattern = attrs.get('pattern', '')

        # Validate regex patterns
        if pattern_type == 'regex':
            try:
                re.compile(pattern)
            except re.error as e:
                raise serializers.ValidationError({
                    'pattern': f'Invalid regular expression: {str(e)}'
                })

        return attrs


class ExcludedURLPatternUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating excluded URL patterns"""

    class Meta:
        model = ExcludedURLPattern
        fields = ('pattern', 'pattern_type', 'description', 'is_active')

    def validate_pattern(self, value):
        """Validate pattern format"""
        if not value or not value.strip():
            raise serializers.ValidationError("Pattern cannot be empty")
        return value.strip()

    def validate(self, attrs):
        """Validate the pattern based on type"""
        pattern_type = attrs.get('pattern_type', self.instance.pattern_type if self.instance else 'prefix')
        pattern = attrs.get('pattern', self.instance.pattern if self.instance else '')

        # Validate regex patterns
        if pattern_type == 'regex':
            try:
                re.compile(pattern)
            except re.error as e:
                raise serializers.ValidationError({
                    'pattern': f'Invalid regular expression: {str(e)}'
                })

        return attrs


class ExcludedURLPatternBulkCreateSerializer(serializers.Serializer):
    """Serializer for bulk creating excluded URL patterns"""
    patterns = serializers.ListField(
        child=ExcludedURLPatternCreateSerializer(),
        min_length=1,
        max_length=100,
        help_text="List of patterns to add"
    )
