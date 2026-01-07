from django.contrib import admin
from .models import IndexingJob


@admin.register(IndexingJob)
class IndexingJobAdmin(admin.ModelAdmin):
    """Indexing Job admin - simplified for MVP"""
    list_display = ('external_job_id', 'site_id', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('external_job_id', 'site_id')
    readonly_fields = ('external_job_id', 'task_id', 'created_at', 'started_at', 'completed_at')
    ordering = ('-created_at',)
