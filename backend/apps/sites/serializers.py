from rest_framework import serializers
from .models import Site, ExcludedURLPattern
import re


class SiteSerializer(serializers.ModelSerializer):
    """Serializer for Site model with full indexing configuration"""
    namespace = serializers.ReadOnlyField(source='get_namespace')
    excluded_patterns_count = serializers.SerializerMethodField()
    active_excluded_patterns_count = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = (
            'id', 'name', 'domain', 'status', 'namespace', 'last_indexed_at',
            'created_at', 'indexed_pages_count', 'total_documents',
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

    class Meta:
        model = Site
        fields = (
            'name', 'domain', 'max_pages', 'crawl_delay', 'respect_robots',
            'include_subdomains', 'scrape_all_subdomains', 'enable_javascript',
            'enable_pdf_processing', 'enable_dynamic_content', 'indexing_config'
        )

    def validate_domain(self, value):
        """Validate domain format"""
        # Ensure domain has protocol if not provided
        if not value.startswith(('http://', 'https://')):
            value = f'https://{value}'
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
        # Automatically set site as active
        validated_data['status'] = 'active'
        return super().create(validated_data)


class SiteUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating site settings"""

    class Meta:
        model = Site
        fields = (
            'status', 'max_pages', 'crawl_delay', 'respect_robots',
            'include_subdomains', 'scrape_all_subdomains', 'enable_javascript',
            'enable_pdf_processing', 'enable_dynamic_content', 'indexing_config'
        )

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
