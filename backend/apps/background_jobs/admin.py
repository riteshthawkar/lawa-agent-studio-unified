from django.contrib import admin
from .models import OutboxEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    """Outbox Event admin"""
    list_display = ('event_type', 'status', 'attempts', 'max_attempts', 'created_at')
    list_filter = ('status', 'event_type', 'created_at')
    search_fields = ('event_type',)
    readonly_fields = ('created_at', 'last_attempt_at')
    ordering = ('-created_at',)
