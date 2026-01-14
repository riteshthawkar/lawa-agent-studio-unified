from django.contrib import admin
from .models import Chatbot


@admin.register(Chatbot)
class ChatbotAdmin(admin.ModelAdmin):
    """Chatbot admin - simplified for MVP"""
    list_display = ('name', 'site', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'description', 'api_key')
    readonly_fields = ('api_key', 'embed_code', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('site', 'name', 'description', 'status')
        }),
        ('API Access', {
            'fields': ('api_key', 'embed_code'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('site')

