from django.contrib import admin
from .models import UsageEvent, Quota


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    """Usage Event admin"""
    list_display = ('type', 'org_id', 'units', 'cost_cents', 'occurred_at')
    list_filter = ('type', 'occurred_at')
    search_fields = ('org_id', 'type')
    readonly_fields = ('occurred_at',)
    ordering = ('-occurred_at',)


@admin.register(Quota)
class QuotaAdmin(admin.ModelAdmin):
    """Quota admin"""
    list_display = ('org_id', 'period_start', 'period_end', 'created_at')
    list_filter = ('period_start', 'period_end', 'created_at')
    search_fields = ('org_id',)
    ordering = ('-created_at',)
