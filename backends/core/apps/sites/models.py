from django.db import models
from apps.core.models import BaseModel
import re


class Site(BaseModel):
    """Site model with indexing configuration"""
    name = models.CharField(max_length=255, blank=True, help_text="Knowledge Base name")
    # Scope uniqueness to organization instead of global
    domain = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('indexing', 'Indexing'),
            ('failed', 'Failed'),
        ],
        default='active'
    )
    # Organization context for multi-tenancy
    org_id = models.UUIDField(null=True, blank=True, db_index=True)

    last_indexed_at = models.DateTimeField(null=True, blank=True)

    # Indexing Statistics
    indexed_pages_count = models.IntegerField(default=0, help_text="Number of pages indexed")
    total_documents = models.IntegerField(default=0, help_text="Total documents in vector store")

    # Indexing Configuration
    indexing_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Indexing configuration settings"
    )

    # Default indexing settings (used when creating new indexing jobs)
    max_pages = models.IntegerField(default=100, help_text="Maximum pages to crawl")
    crawl_delay = models.FloatField(default=1.0, help_text="Delay between page requests in seconds")
    respect_robots = models.BooleanField(default=True, help_text="Respect robots.txt rules")
    include_subdomains = models.BooleanField(default=False, help_text="Include subdomains in crawl")
    scrape_all_subdomains = models.BooleanField(default=False, help_text="Auto-discover and scrape all subdomains")

    # Advanced indexing options
    enable_javascript = models.BooleanField(default=True, help_text="Enable JavaScript rendering")
    enable_pdf_processing = models.BooleanField(default=True, help_text="Process PDF files")
    enable_dynamic_content = models.BooleanField(default=False, help_text="Handle infinite scroll and dynamic content")

    # Dynamic Namespace (for Zero-Downtime Re-indexing)
    active_namespace = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Currently active Pinecone namespace"
    )

    class Meta:
        db_table = 'sites'
        verbose_name = 'Site'
        verbose_name_plural = 'Sites'
        indexes = [
            models.Index(fields=['domain']),
            models.Index(fields=['status']),
            # Composite indexes for multi-tenant queries
            models.Index(fields=['org_id', 'status'], name='sites_org_status_idx'),
            models.Index(fields=['org_id', 'created_at'], name='sites_org_created_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['domain', 'org_id'],
                name='unique_site_domain_per_org'
            )
        ]

    def __str__(self):
        return f"{self.domain}"

    def get_namespace(self):
        """Get the namespace for this site"""
        # Return DB stored namespace if available, else fallback to default format
        if self.active_namespace:
            return self.active_namespace
        return f"site_{self.id}"

    def get_excluded_patterns(self):
        """Get list of active excluded URL patterns for this site"""
        return list(
            ExcludedURLPattern.objects.filter(
                site_id=self.id,
                is_active=True
            ).values_list('pattern', flat=True)
        )


class ExcludedURLPattern(BaseModel):
    """
    Stores URL patterns to exclude from indexing.
    Supports multiple pattern types for flexible exclusion rules.
    """
    PATTERN_TYPE_CHOICES = [
        ('exact', 'Exact Match'),
        ('prefix', 'Prefix Match'),
        ('suffix', 'Suffix Match'),
        ('contains', 'Contains'),
        ('regex', 'Regular Expression'),
    ]

    # Relationships
    site_id = models.UUIDField(db_index=True, help_text="Site to apply exclusion to")
    org_id = models.UUIDField(null=True, blank=True, db_index=True, help_text="Organization context")

    # Pattern definition
    pattern = models.CharField(
        max_length=2000,
        help_text="URL pattern to exclude"
    )
    pattern_type = models.CharField(
        max_length=20,
        choices=PATTERN_TYPE_CHOICES,
        default='prefix',
        help_text="How to match the pattern"
    )

    # Metadata
    description = models.CharField(
        max_length=500,
        blank=True,
        help_text="Description or reason for exclusion"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this exclusion is currently active"
    )

    # Statistics
    urls_matched = models.IntegerField(
        default=0,
        help_text="Number of URLs matched by this pattern in last indexing"
    )

    class Meta:
        db_table = 'excluded_url_patterns'
        verbose_name = 'Excluded URL Pattern'
        verbose_name_plural = 'Excluded URL Patterns'
        indexes = [
            models.Index(fields=['site_id', 'is_active']),
            models.Index(fields=['org_id', 'site_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['site_id', 'pattern', 'pattern_type'],
                name='uq_excluded_pattern_per_site'
            ),
        ]

    def __str__(self):
        return f"{self.pattern_type}: {self.pattern}"

    def matches_url(self, url):
        """Check if a URL matches this exclusion pattern"""
        try:
            if self.pattern_type == 'exact':
                return url == self.pattern
            elif self.pattern_type == 'prefix':
                return url.startswith(self.pattern)
            elif self.pattern_type == 'suffix':
                return url.endswith(self.pattern)
            elif self.pattern_type == 'contains':
                return self.pattern in url
            elif self.pattern_type == 'regex':
                # Use re.search to find matches anywhere, not just at the start
                return bool(re.search(self.pattern, url))
            return False
        except Exception:
            return False

    def validate_pattern(self):
        """Validate the pattern (especially for regex)"""
        if self.pattern_type == 'regex':
            try:
                re.compile(self.pattern)
                return True, None
            except re.error as e:
                return False, str(e)
        return True, None
