from django.contrib import admin
from .models import Organization, Membership


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Organization admin"""
    list_display = ('name', 'slug', 'status', 'plan_tier', 'created_at')
    list_filter = ('status', 'plan_tier', 'created_at')
    search_fields = ('name', 'slug')
    ordering = ('-created_at',)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    """Membership admin"""
    list_display = ('user', 'organization', 'role', 'created_at')
    list_filter = ('role', 'created_at')
    search_fields = ('user__email', 'organization__name')
    ordering = ('-created_at',)
