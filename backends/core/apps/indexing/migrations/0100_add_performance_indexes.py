"""
Add performance indexes for indexing models.

This migration adds missing composite and single-column indexes
to improve query performance for common access patterns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('indexing', '0008_indexingjob_org_id'),
    ]

    operations = [
        # IndexingJob indexes
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['org_id', 'status'],
                name='idx_job_org_status_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['org_id', 'created_at'],
                name='idx_job_org_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['site_id', 'status'],
                name='idx_job_site_status_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['site_id', 'created_at'],
                name='idx_job_site_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['status', 'created_at'],
                name='idx_job_status_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['external_job_id'],
                name='idx_job_external_id_idx',
                condition=models.Q(external_job_id__isnull=False)
            ),
        ),
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['task_id'],
                name='idx_job_task_id_idx',
                condition=models.Q(task_id__isnull=False)
            ),
        ),

        # Partial index for active/in-progress jobs (frequently queried)
        migrations.AddIndex(
            model_name='indexingjob',
            index=models.Index(
                fields=['created_at'],
                name='idx_job_active_created_idx',
                condition=models.Q(status__in=['pending', 'processing', 'indexing'])
            ),
        ),
    ]
