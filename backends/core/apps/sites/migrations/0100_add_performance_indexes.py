"""
Add performance indexes for sites models.

This migration adds missing composite and single-column indexes
to improve query performance for common access patterns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0008_fix_status_check_constraint'),
    ]

    operations = [
        # Site indexes
        migrations.AddIndex(
            model_name='site',
            index=models.Index(
                fields=['org_id', 'status'],
                name='site_org_status_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='site',
            index=models.Index(
                fields=['org_id', 'created_at'],
                name='site_org_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='site',
            index=models.Index(
                fields=['status', 'last_indexed_at'],
                name='site_status_indexed_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='site',
            index=models.Index(
                fields=['domain'],
                name='site_domain_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='site',
            index=models.Index(
                fields=['active_namespace'],
                name='site_active_namespace_idx',
                condition=models.Q(active_namespace__isnull=False)
            ),
        ),
    ]
