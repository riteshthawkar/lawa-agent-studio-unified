from django.contrib import admin
from .models import ChatSession, ChatMessage


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    """Chat Session admin"""
    list_display = ('session_key', 'org_id', 'chatbot_id', 'is_closed', 'created_at')
    list_filter = ('closed_at', 'created_at')
    search_fields = ('session_key', 'org_id', 'chatbot_id')
    readonly_fields = ('session_key', 'created_at', 'closed_at')
    ordering = ('-created_at',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Chat Message admin"""
    list_display = ('session', 'role', 'content_preview', 'tokens_in', 'tokens_out', 'created_at')
    list_filter = ('role', 'created_at')
    search_fields = ('session__session_key', 'content')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    
    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content Preview'
