"""
Models for FAQ and Feedback support features
"""
import uuid
from django.db import models
from django.conf import settings
from apps.core.models import BaseModel


class FAQCategory(BaseModel):
    """Categories for organizing FAQs"""
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Lucide icon name")
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'support_faq_categories'
        ordering = ['order', 'name']
        verbose_name_plural = 'FAQ Categories'

    def __str__(self):
        return self.name


class FAQ(BaseModel):
    """Frequently Asked Questions"""
    category = models.ForeignKey(
        FAQCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faqs'
    )
    question = models.CharField(max_length=500)
    answer = models.TextField()
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False, help_text="Show on main FAQ page")
    helpful_count = models.IntegerField(default=0)
    not_helpful_count = models.IntegerField(default=0)
    view_count = models.IntegerField(default=0)
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'support_faqs'
        ordering = ['category__order', 'order', '-is_featured']
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'

    def __str__(self):
        return self.question[:100]

    def mark_helpful(self):
        self.helpful_count += 1
        self.save(update_fields=['helpful_count', 'updated_at'])

    def mark_not_helpful(self):
        self.not_helpful_count += 1
        self.save(update_fields=['not_helpful_count', 'updated_at'])

    def increment_view(self):
        self.view_count += 1
        self.save(update_fields=['view_count'])


class Feedback(BaseModel):
    """User feedback submissions"""
    FEEDBACK_TYPES = [
        ('general', 'General Feedback'),
        ('bug', 'Bug Report'),
        ('feature', 'Feature Request'),
        ('complaint', 'Complaint'),
        ('praise', 'Praise'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('in_review', 'In Review'),
        ('acknowledged', 'Acknowledged'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    # User info
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_feedback_submissions'
    )
    org_id = models.UUIDField(null=True, blank=True, db_index=True)
    email = models.EmailField(blank=True, help_text="For anonymous feedback")

    # Feedback content
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES, default='general')
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()

    # Context
    page_url = models.URLField(blank=True, help_text="Page where feedback was submitted")
    user_agent = models.TextField(blank=True)
    screen_resolution = models.CharField(max_length=20, blank=True)

    # For bug reports
    steps_to_reproduce = models.TextField(blank=True)
    expected_behavior = models.TextField(blank=True)
    actual_behavior = models.TextField(blank=True)

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')

    # Admin response
    admin_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_feedback'
    )

    class Meta:
        db_table = 'support_feedback'
        ordering = ['-created_at']
        verbose_name_plural = 'Feedback'

    def __str__(self):
        return f"{self.get_feedback_type_display()}: {self.subject or self.message[:50]}"


class HelpArticle(BaseModel):
    """Help center articles"""
    ARTICLE_TYPES = [
        ('getting_started', 'Getting Started'),
        ('tutorial', 'Tutorial'),
        ('guide', 'Guide'),
        ('troubleshooting', 'Troubleshooting'),
        ('reference', 'Reference'),
    ]

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    article_type = models.CharField(max_length=20, choices=ARTICLE_TYPES, default='guide')
    summary = models.TextField(blank=True, help_text="Brief description for listings")
    content = models.TextField(help_text="Markdown content")
    icon = models.CharField(max_length=50, blank=True, help_text="Lucide icon name")

    # Organization
    category = models.ForeignKey(
        FAQCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articles'
    )
    order = models.IntegerField(default=0)

    # Status
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    # Analytics
    view_count = models.IntegerField(default=0)
    helpful_count = models.IntegerField(default=0)
    not_helpful_count = models.IntegerField(default=0)

    # Related content
    related_articles = models.ManyToManyField('self', blank=True, symmetrical=False)
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'support_help_articles'
        ordering = ['category__order', 'order', 'title']

    def __str__(self):
        return self.title

    def increment_view(self):
        self.view_count += 1
        self.save(update_fields=['view_count'])
