from django.contrib import admin
from .models import Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    """Site admin - simplified for MVP"""
    list_display = ('domain', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('domain',)
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
