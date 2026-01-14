"""
Admin configuration for support models
"""
from django.contrib import admin
from .models import FAQ, FAQCategory, Feedback, HelpArticle


@admin.register(FAQCategory)
class FAQCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['order', 'name']


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ['question', 'category', 'is_active', 'is_featured', 'helpful_count', 'view_count']
    list_filter = ['is_active', 'is_featured', 'category']
    search_fields = ['question', 'answer']
    raw_id_fields = ['category']
    ordering = ['category__order', 'order']


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['subject_or_message', 'feedback_type', 'status', 'priority', 'user', 'created_at']
    list_filter = ['feedback_type', 'status', 'priority', 'created_at']
    search_fields = ['subject', 'message', 'user__email']
    raw_id_fields = ['user', 'resolved_by']
    readonly_fields = ['user', 'org_id', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def subject_or_message(self, obj):
        return obj.subject if obj.subject else obj.message[:50]
    subject_or_message.short_description = 'Subject'


@admin.register(HelpArticle)
class HelpArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'article_type', 'category', 'is_active', 'is_featured', 'view_count']
    list_filter = ['is_active', 'is_featured', 'article_type', 'category']
    search_fields = ['title', 'summary', 'content']
    prepopulated_fields = {'slug': ('title',)}
    raw_id_fields = ['category']
    filter_horizontal = ['related_articles']
    ordering = ['category__order', 'order', 'title']
