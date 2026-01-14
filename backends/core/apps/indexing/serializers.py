from rest_framework import serializers
from .models import IndexingJob, IndexedPage


class IndexingJobSerializer(serializers.ModelSerializer):
    """Serializer for IndexingJob model with API compliance - simplified for MVP"""
    progress = serializers.ReadOnlyField()
    result = serializers.ReadOnlyField()
    duration = serializers.ReadOnlyField()
    page_counts = serializers.SerializerMethodField()
    documents_indexed = serializers.SerializerMethodField()
    
    site_domain = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()
    
    class Meta:
        model = IndexingJob
        fields = (
            'id', 'site_id', 'site_domain', 'task_id', 'external_job_id',
            'status', 'progress', 'progress_percentage', 'result', 'error_message', 
            'created_at', 'started_at', 'completed_at', 'duration', 'url', 'max_pages',
            'urls_collected', 'urls_processed', 'documents_indexed',
            'page_counts', 'can_cancel', 'can_retry'
        )
        read_only_fields = (
            'id', 'site_id', 'task_id', 'external_job_id',
            'status', 'progress', 'result', 'error_message', 'created_at',
            'started_at', 'completed_at', 'duration', 'urls_collected',
            'urls_processed', 'documents_indexed'
        )

    def get_page_counts(self, obj):
        """Get summary of page statuses from IndexedPage records (accurate page counts)
        Falls back to stored urls_collected for historical jobs where IndexedPage records may be missing
        """
        from .models import IndexedPage
        
        # Count from IndexedPage database (most accurate for current job)
        def count_status(status):
            return IndexedPage.objects.filter(indexing_job_id=obj.id, status=status).count()
        
        indexed_count = count_status('indexed')
        failed_count = count_status('failed')
        skipped_count = count_status('skipped')
        total_count = IndexedPage.objects.filter(indexing_job_id=obj.id).count()
        
        # For historical jobs where IndexedPage records were replaced by newer indexing runs,
        # fall back to urls_collected (unique page count) not documents_indexed (chunk count)
        if total_count == 0 and obj.urls_collected and obj.urls_collected > 0:
            indexed_count = obj.urls_collected
            total_count = obj.urls_collected
            
        return {
            'indexed': indexed_count,
            'failed': failed_count,
            'skipped': skipped_count,
            'total': total_count
        }

    def get_documents_indexed(self, obj):
        """Get documents_indexed from page_counts for consistency"""
        return self.get_page_counts(obj)['indexed']

    def get_site_domain(self, obj):
        """Get the domain of the site associated with this job"""
        from apps.sites.models import Site
        try:
            site = Site.objects.get(id=obj.site_id)
            return site.domain
        except:
            return None

    def get_progress_percentage(self, obj):
        """Calculate progress percentage"""
        if obj.status == 'completed':
            return 100
        if obj.status == 'failed':
            return 0
        if not obj.max_pages or obj.max_pages == 0:
            return 0
        return min(round((obj.urls_processed / obj.max_pages) * 100, 2), 99.99)

    def get_can_cancel(self, obj):
        """Check if job can be cancelled"""
        return obj.status in ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']

    def get_can_retry(self, obj):
        """Check if job can be retried"""
        return obj.status in ['failed', 'cancelled']


class IndexingJobListSerializer(serializers.ModelSerializer):
    """Simplified serializer for task listing - matches actual model fields"""
    progress = serializers.ReadOnlyField()
    result = serializers.ReadOnlyField()
    duration = serializers.ReadOnlyField()
    page_counts = serializers.SerializerMethodField()
    documents_indexed = serializers.SerializerMethodField()
    
    site_domain = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()
    
    class Meta:
        model = IndexingJob
        fields = (
            'id', 'site_id', 'site_domain', 'task_id', 'external_job_id', 'url',
            'status', 'progress', 'progress_percentage', 'result', 'error_message',
            'created_at', 'started_at', 'completed_at', 'duration',
            'page_counts', 'documents_indexed', 'can_cancel', 'can_retry'
        )

    def get_page_counts(self, obj):
        """Get summary of page statuses from IndexedPage records (accurate page counts)
        Falls back to stored urls_collected for historical jobs where IndexedPage records may be missing
        """
        from .models import IndexedPage
        
        # Count from IndexedPage database (most accurate for current job)
        def count_status(status):
            return IndexedPage.objects.filter(indexing_job_id=obj.id, status=status).count()
        
        indexed_count = count_status('indexed')
        failed_count = count_status('failed')
        skipped_count = count_status('skipped')
        total_count = IndexedPage.objects.filter(indexing_job_id=obj.id).count()
        
        # For historical jobs where IndexedPage records were replaced by newer indexing runs,
        # fall back to urls_collected (unique page count) not documents_indexed (chunk count)
        if total_count == 0 and obj.urls_collected and obj.urls_collected > 0:
            indexed_count = obj.urls_collected
            total_count = obj.urls_collected
            
        return {
            'indexed': indexed_count,
            'failed': failed_count,
            'skipped': skipped_count,
            'total': total_count
        }

    def get_documents_indexed(self, obj):
        """Get documents_indexed from page_counts for consistency"""
        return self.get_page_counts(obj)['indexed']

    def get_site_domain(self, obj):
        return IndexingJobSerializer.get_site_domain(self, obj)

    def get_progress_percentage(self, obj):
        return IndexingJobSerializer.get_progress_percentage(self, obj)

    def get_can_cancel(self, obj):
        return IndexingJobSerializer.get_can_cancel(self, obj)

    def get_can_retry(self, obj):
        return IndexingJobSerializer.get_can_retry(self, obj)


class IndexingJobCreateSerializer(serializers.Serializer):
    """Serializer for creating indexing jobs with API compliance"""
    # Required fields
    url = serializers.URLField(help_text="Starting URL to index")
    max_pages = serializers.IntegerField(min_value=1, max_value=10000, default=100)
    
    # Optional configuration
    allowed_domains = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Additional allowed domains"
    )
    excluded_subdomains = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Subdomains to skip"
    )
    pinecone_index = serializers.CharField(required=False, allow_blank=True)
    embed_model = serializers.CharField(required=False, allow_blank=True)
    streaming_mode = serializers.BooleanField(default=True)
    
    # Multi-tenancy
    tenant_id = serializers.CharField(required=False, allow_blank=True)
    site_id = serializers.CharField(required=False, allow_blank=True)
    external_job_id = serializers.CharField(required=False, allow_blank=True)
    callback_url = serializers.URLField(required=False, allow_blank=True)
    
    # Namespace configuration
    use_namespaces = serializers.BooleanField(default=True)
    namespace_prefix = serializers.CharField(default='website_domain')
    namespace_override = serializers.CharField(required=False, allow_blank=True)
    
    # Custom configuration
    custom_config = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        """Validate indexing job parameters"""
        # Validate URL format
        url = attrs.get('url', '')
        if not url.startswith(('http://', 'https://')):
            raise serializers.ValidationError("URL must start with http:// or https://")
        
        # Validate max_pages is reasonable
        max_pages = attrs.get('max_pages', 100)
        if max_pages > 10000:
            raise serializers.ValidationError("max_pages cannot exceed 10000")
        
        return attrs


class IndexingJobUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating indexing job status (webhook)"""
    
    class Meta:
        model = IndexingJob
        fields = ('status', 'phase1_result', 'phase2_result', 'error_message')

    def validate_status(self, value):
        """Validate status transitions"""
        instance = self.instance
        if instance:
            valid_transitions = {
                'queued': ['running', 'cancelled'],
                'running': ['completed', 'failed', 'cancelled'],
                'completed': [],
                'failed': [],
                'cancelled': [],
            }

            if value not in valid_transitions.get(instance.status, []):
                raise serializers.ValidationError(
                    f"Invalid status transition from {instance.status} to {value}"
                )

        return value


# Bug #26 fix: IndexedPage serializers for per-URL visibility

class IndexedPageSerializer(serializers.ModelSerializer):
    """Serializer for IndexedPage model - shows individual URL indexing results"""

    class Meta:
        model = IndexedPage
        fields = (
            'id', 'site_id', 'indexing_job_id', 'url', 'title',
            'content_type', 'status', 'document_count', 'content_size_bytes',
            'error_message', 'retry_count', 'discovered_at', 'processed_at',
            'user_added', 'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'site_id', 'indexing_job_id', 'url_hash',
            'discovered_at', 'processed_at', 'created_at', 'updated_at'
        )


class IndexedPageListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing indexed pages"""

    class Meta:
        model = IndexedPage
        fields = (
            'id', 'url', 'title', 'content_type', 'status',
            'document_count', 'content_size_bytes', 'error_message',
            'discovered_at', 'processed_at', 'user_added', 'updated_at'
        )


class IndexedPageCreateSerializer(serializers.Serializer):
    """Serializer for manually adding URLs to be indexed"""
    url = serializers.URLField(help_text="URL to add for indexing")

    def validate_url(self, value):
        """Validate URL format"""
        if not value.startswith(('http://', 'https://')):
            raise serializers.ValidationError("URL must start with http:// or https://")
        return value
