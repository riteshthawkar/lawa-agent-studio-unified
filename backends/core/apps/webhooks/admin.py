from django.contrib import admin
from .models import WebhookEvent, AuditLog


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    """Webhook Event admin"""
    list_display = ('kind', 'target_url', 'result_status', 'attempts', 'created_at')
    list_filter = ('kind', 'result_status', 'created_at')
    search_fields = ('target_url', 'kind')
    readonly_fields = ('created_at', 'last_attempt_at')
    ordering = ('-created_at',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Audit Log admin"""
    list_display = ('action', 'target_type', 'target_id', 'actor_user_id', 'created_at')
    list_filter = ('action', 'target_type', 'created_at')
    search_fields = ('org_id', 'action', 'target_type')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
