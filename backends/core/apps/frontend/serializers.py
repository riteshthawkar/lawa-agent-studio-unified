"""
Serializers for frontend API endpoints
"""
from rest_framework import serializers
from apps.sites.models import Site
from apps.indexing.models import IndexingJob
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage


class DashboardStatsSerializer(serializers.Serializer):
    """Serializer for dashboard statistics"""
    organization = serializers.DictField()
    sites = serializers.DictField()
    indexing = serializers.DictField()
    chatbots = serializers.DictField()
    chat_sessions = serializers.DictField()
    usage = serializers.DictField()
    last_updated = serializers.DateTimeField()


class SiteManagementSerializer(serializers.ModelSerializer):
    """Serializer for site management interface with full configuration"""
    indexing_jobs_count = serializers.SerializerMethodField()
    active_indexing_jobs = serializers.SerializerMethodField()
    chatbots_count = serializers.SerializerMethodField()
    last_indexing_job = serializers.SerializerMethodField()
    chatbots = serializers.SerializerMethodField()
    excluded_patterns_count = serializers.SerializerMethodField()
    active_excluded_patterns_count = serializers.SerializerMethodField()
    indexed_pages_count = serializers.SerializerMethodField()  # Dynamic count

    class Meta:
        model = Site
        fields = (
            'id', 'name', 'domain', 'status', 'last_indexed_at', 'created_at', 'updated_at',
            'indexed_pages_count', 'total_documents',
            'max_pages', 'crawl_delay', 'respect_robots', 'include_subdomains',
            'scrape_all_subdomains', 'enable_javascript', 'enable_pdf_processing',
            'enable_dynamic_content', 'indexing_config',
            'indexing_jobs_count', 'active_indexing_jobs', 'chatbots_count',
            'chatbots', 'last_indexing_job',
            'excluded_patterns_count', 'active_excluded_patterns_count'
        )
    
    def get_indexing_jobs_count(self, obj):
        # Use annotated value if available (from optimized query), otherwise fallback to direct query
        return getattr(obj, 'total_jobs', IndexingJob.objects.filter(site_id=obj.id).count())

    def get_active_indexing_jobs(self, obj):
        # Use annotated value if available (from optimized query), otherwise fallback to direct query
        return getattr(obj, 'active_jobs', IndexingJob.objects.filter(
            site_id=obj.id,
            status__in=['queued', 'processing', 'collecting_urls', 'processing_urls']
        ).count())

    def get_chatbots_count(self, obj):
        # Use annotated value if available (from optimized query), otherwise use related manager
        return getattr(obj, 'total_chatbots', obj.chatbots.count())
    
    def get_indexed_pages_count(self, obj):
        """Compute actual indexed pages count from IndexedPage records for this site"""
        from apps.indexing.models import IndexedPage
        return IndexedPage.objects.filter(site_id=obj.id, status='indexed').count()
    
    def get_last_indexing_job(self, obj):
        last_job = IndexingJob.objects.filter(site_id=obj.id).order_by('-created_at').first()
        if last_job:
            return {
                'id': str(last_job.id),
                'status': last_job.status,
                'created_at': last_job.created_at.isoformat(),
                'documents_indexed': last_job.documents_indexed,
                'duration': last_job.duration
            }
        return None

    def get_chatbots(self, obj):
        """Get list of chatbots for this site"""
        chatbots = obj.chatbots.order_by('-created_at')[:5]
        return [
            {
                'id': str(cb.id),
                'name': cb.name,
                'status': cb.status,
                'created_at': cb.created_at.isoformat()
            }
            for cb in chatbots
        ]
    
    def get_excluded_patterns_count(self, obj):
        """Return total count of excluded URL patterns for this site"""
        from apps.sites.models import ExcludedURLPattern
        return ExcludedURLPattern.objects.filter(site_id=obj.id).count()
    
    def get_active_excluded_patterns_count(self, obj):
        """Return count of active excluded URL patterns for this site"""
        from apps.sites.models import ExcludedURLPattern
        return ExcludedURLPattern.objects.filter(site_id=obj.id, is_active=True).count()


class IndexingJobManagementSerializer(serializers.ModelSerializer):
    """Serializer for indexing job management interface - simplified for MVP"""
    site_domain = serializers.SerializerMethodField()
    site_name = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    duration_formatted = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()

    class Meta:
        model = IndexingJob
        fields = (
            'id', 'site_id', 'site_domain', 'site_name',
            'task_id', 'external_job_id', 'status', 'url', 'max_pages',
            'urls_collected', 'urls_processed', 'documents_indexed', 'pages_indexed',
            'progress_percentage', 'duration_formatted', 'error_message',
            'created_at', 'started_at', 'completed_at', 'can_cancel', 'can_retry'
        )

    def get_site_domain(self, obj):
        # Use context sites_map if available (bulk prefetched), otherwise fallback to direct query
        sites_map = self.context.get('sites_map', {}) if self.context else {}
        if str(obj.site_id) in sites_map:
            return sites_map[str(obj.site_id)].domain
        if hasattr(obj, 'site') and obj.site:
            return obj.site.domain
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.domain
        except Site.DoesNotExist:
            return 'Unknown Site'

    def get_site_name(self, obj):
        # Use context sites_map if available (bulk prefetched), otherwise fallback to direct query
        sites_map = self.context.get('sites_map', {}) if self.context else {}
        if str(obj.site_id) in sites_map:
            site = sites_map[str(obj.site_id)]
            return site.name if site.name else site.domain
        if hasattr(obj, 'site') and obj.site:
            return obj.site.name if obj.site.name else obj.site.domain
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.name if site.name else site.domain
        except Site.DoesNotExist:
            return 'Unknown Site'

    def get_progress_percentage(self, obj):
        if obj.status == 'completed':
            return 100
        elif obj.status in ['queued', 'failed', 'cancelled']:
            return 0
        elif obj.max_pages > 0:
            return min(int((obj.urls_processed / obj.max_pages) * 100), 99)
        return 0
    
    def get_duration_formatted(self, obj):
        if obj.duration:
            hours, remainder = divmod(obj.duration, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return None
    
    def get_can_cancel(self, obj):
        return obj.status in ['queued', 'processing', 'collecting_urls', 'processing_urls']
    
    def get_can_retry(self, obj):
        return obj.status == 'failed'


class IndexingJobHistorySerializer(serializers.ModelSerializer):
    """Serializer for job history listing with page statistics"""
    site_domain = serializers.SerializerMethodField()
    site_name = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    duration_formatted = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()
    page_counts = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = IndexingJob
        fields = (
            'id', 'site_id', 'site_domain', 'site_name',
            'task_id', 'external_job_id', 'status', 'status_label',
            'url', 'max_pages', 'target_namespace',
            'urls_collected', 'urls_processed', 'documents_indexed', 'pages_indexed',
            'progress_percentage', 'duration_formatted', 'duration_seconds',
            'error_message', 'page_counts',
            'created_at', 'started_at', 'completed_at',
            'can_cancel', 'can_retry'
        )

    def get_site_domain(self, obj):
        site = self.context.get('site') if self.context else None
        if site:
            return site.domain
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.domain
        except Site.DoesNotExist:
            return 'Unknown'

    def get_site_name(self, obj):
        site = self.context.get('site') if self.context else None
        if site:
            return site.name if site.name else site.domain
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.name if site.name else site.domain
        except Site.DoesNotExist:
            return 'Unknown'

    def get_progress_percentage(self, obj):
        progress = obj.progress
        return progress.get('progress_percentage', 0)

    def get_duration_formatted(self, obj):
        if obj.duration:
            hours, remainder = divmod(obj.duration, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return None

    def get_duration_seconds(self, obj):
        return obj.duration

    def get_can_cancel(self, obj):
        return obj.status in ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']

    def get_can_retry(self, obj):
        return obj.status in ['failed', 'cancelled']

    def get_page_counts(self, obj):
        page_counts = self.context.get('page_counts', {}) if self.context else {}
        return page_counts.get(str(obj.id), {
            'total': 0,
            'indexed': 0,
            'failed': 0,
            'skipped': 0
        })

    def get_status_label(self, obj):
        status_labels = {
            'queued': 'Queued',
            'processing': 'Processing',
            'collecting_urls': 'Collecting URLs',
            'processing_urls': 'Processing URLs',
            'running': 'Running',
            'completed': 'Completed',
            'failed': 'Failed',
            'cancelled': 'Cancelled'
        }
        return status_labels.get(obj.status, obj.status.title())


class IndexingJobDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for individual job view"""
    site_domain = serializers.SerializerMethodField()
    site_name = serializers.SerializerMethodField()
    progress = serializers.ReadOnlyField()
    progress_percentage = serializers.SerializerMethodField()
    duration = serializers.ReadOnlyField()
    duration_formatted = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()

    class Meta:
        model = IndexingJob
        fields = (
            'id', 'site_id', 'site_domain', 'site_name',
            'task_id', 'external_job_id', 'status', 'status_label',
            'url', 'max_pages', 'target_namespace',
            'urls_collected', 'urls_processed', 'documents_indexed', 'pages_indexed',
            'progress', 'progress_percentage', 'duration', 'duration_formatted',
            'error_message', 'callback_url',
            'phase1_result', 'phase2_result',
            'created_at', 'started_at', 'completed_at',
            'can_cancel', 'can_retry'
        )

    def get_site_domain(self, obj):
        site = self.context.get('site') if self.context else None
        if site:
            return site.domain
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.domain
        except Site.DoesNotExist:
            return 'Unknown'

    def get_site_name(self, obj):
        site = self.context.get('site') if self.context else None
        if site:
            return site.name if site.name else site.domain
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.name if site.name else site.domain
        except Site.DoesNotExist:
            return 'Unknown'

    def get_duration_formatted(self, obj):
        if obj.duration:
            hours, remainder = divmod(obj.duration, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return None

    def get_progress_percentage(self, obj):
        """Calculate progress percentage based on job status and URL counts."""
        progress = obj.progress
        if progress and isinstance(progress, dict):
            return progress.get('progress_percentage', 0)
        # Fallback: calculate from URL counts
        if obj.status == 'completed':
            return 100
        if obj.urls_collected and obj.urls_processed:
            return min(int((obj.urls_processed / obj.urls_collected) * 100), 100)
        return 0

    def get_status_label(self, obj):
        status_labels = {
            'queued': 'Queued',
            'processing': 'Processing',
            'collecting_urls': 'Collecting URLs',
            'processing_urls': 'Processing URLs',
            'running': 'Running',
            'completed': 'Completed',
            'failed': 'Failed',
            'cancelled': 'Cancelled'
        }
        return status_labels.get(obj.status, obj.status.title())

    def get_can_cancel(self, obj):
        return obj.status in ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']

    def get_can_retry(self, obj):
        return obj.status in ['failed', 'cancelled']


class ChatbotManagementSerializer(serializers.ModelSerializer):
    """Serializer for chatbot management interface - simplified for MVP"""
    # Expose site_id for backward compatibility (from ForeignKey)
    site_id = serializers.UUIDField(source='site.id', read_only=True)
    site_domain = serializers.SerializerMethodField()
    site_name = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    sessions_count = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()

    class Meta:
        model = Chatbot
        fields = (
            'id', 'site_id', 'site_domain', 'site_name',
            'name', 'description', 'status', 'is_active',
            'api_key', 'embed_code', 'primary_color', 'text_color',
            'chatbot_tone', 'response_length',
            'sessions_count', 'last_activity',
            'created_at', 'updated_at'
        )
    
    def get_site_domain(self, obj):
        # Use FK relationship if available
        if obj.site:
            return obj.site.domain
        return 'Unknown Site'

    def get_site_name(self, obj):
        # Use FK relationship if available
        if obj.site:
            return obj.site.name if obj.site.name else obj.site.domain
        return 'Unknown Site'

    def get_sessions_count(self, obj):
        # Use annotated value if available (from optimized query), otherwise fallback to direct query
        if hasattr(obj, 'recent_sessions_count'):
            return obj.recent_sessions_count
        # Get sessions count for last 30 days
        from django.utils import timezone
        from datetime import timedelta
        thirty_days_ago = timezone.now() - timedelta(days=30)
        return ChatSession.objects.filter(
            chatbot_id=obj.id,
            created_at__gte=thirty_days_ago
        ).count()

    def get_last_activity(self, obj):
        # Use context last_sessions if available (bulk prefetched), otherwise fallback to direct query
        last_sessions = self.context.get('last_sessions', {}) if self.context else {}
        if str(obj.id) in last_sessions:
            last_created = last_sessions[str(obj.id)]
            return last_created.isoformat() if last_created else None

        last_session = ChatSession.objects.filter(
            chatbot_id=obj.id
        ).order_by('-created_at').first()
        if last_session:
            return last_session.created_at.isoformat()
        return None


class UserProfileSerializer(serializers.Serializer):
    """Serializer for user profile information"""
    user = serializers.DictField()
    organization = serializers.DictField()
    activity_summary = serializers.DictField()


class BulkActionSerializer(serializers.Serializer):
    """Serializer for bulk actions"""
    action_type = serializers.ChoiceField(choices=[
        'delete', 'verify', 'block', 'activate', 'deactivate', 'cancel', 'retry'
    ])
    resource_type = serializers.ChoiceField(choices=[
        'sites', 'indexing_jobs', 'chatbots'
    ])
    resource_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100
    )
    
    def validate(self, attrs):
        action_type = attrs.get('action_type')
        resource_type = attrs.get('resource_type')
        
        # Validate action-resource combinations
        valid_combinations = {
            'sites': ['delete', 'verify', 'block'],
            'indexing_jobs': ['cancel', 'retry'],
            'chatbots': ['activate', 'deactivate']
        }
        
        if resource_type in valid_combinations:
            if action_type not in valid_combinations[resource_type]:
                raise serializers.ValidationError(
                    f"Action '{action_type}' is not valid for resource type '{resource_type}'"
                )
        
        return attrs


class SiteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating sites from frontend - simplified for MVP"""
    
    class Meta:
        model = Site
        fields = ('domain',)
    
    def validate_domain(self, value):
        """Validate domain format"""
        if not value.startswith(('http://', 'https://')):
            value = f"https://{value}"
        
        # Basic URL validation
        from django.core.validators import URLValidator
        validator = URLValidator()
        try:
            validator(value)
        except:
            raise serializers.ValidationError("Invalid domain format")
        
        return value
    


class IndexingJobCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating indexing jobs from frontend - simplified for MVP"""
    
    class Meta:
        model = IndexingJob
        fields = ('url', 'max_pages')
    
    def validate_max_pages(self, value):
        """Validate max pages"""
        if value < 1 or value > 10000:
            raise serializers.ValidationError("Max pages must be between 1 and 10000")
        return value
    
    def validate_url(self, value):
        """Validate URL format"""
        from django.core.validators import URLValidator
        validator = URLValidator()
        try:
            validator(value)
        except:
            raise serializers.ValidationError("Invalid URL format")
        return value


class ChatbotCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating chatbots from frontend - includes all configuration fields"""
    
    class Meta:
        model = Chatbot
        fields = (
            'name', 'description',
            # AI Configuration
            'config',
            # Chatbot Personality
            'chatbot_tone', 'response_length',
            # Widget Configuration
            'theme', 'position', 'primary_color', 'text_color', 'auto_open',
            'greeting_message', 'placeholder_text',
            # Advanced Configuration
            'enable_typing_indicator', 'enable_sound_notifications',
            'max_retries', 'reconnect_delay',
            # Language
            'language'
        )
    
    def validate_name(self, value):
        """Validate chatbot name"""
        if not value or not value.strip():
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
        import re
        if not value:
            return '#2563eb'  # Default color
        if not re.match(r'^#[0-9A-Fa-f]{6}$', value):
            raise serializers.ValidationError("Invalid hex color format. Use format like #3b82f6")
        return value

    def validate_text_color(self, value):
        """Validate hex color format for text color"""
        import re
        if not value:
            return '#ffffff'  # Default text color
        if not re.match(r'^#[0-9A-Fa-f]{6}$', value):
            raise serializers.ValidationError("Invalid hex color format for text color. Use format like #ffffff")
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

    def validate_config(self, value):
        """Validate config field structure"""
        if not value:
            return {'model': 'gpt-4o', 'temperature': 0.7, 'system_prompt': 'You are a helpful AI assistant.'}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Config must be a dictionary")
        return value

