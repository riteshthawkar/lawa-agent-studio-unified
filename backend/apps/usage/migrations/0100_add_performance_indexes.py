"""
Add performance indexes for usage models.

This migration adds missing composite and single-column indexes
to improve query performance for common access patterns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usage', '0001_initial'),
    ]

    operations = [
        # UsageEvent indexes
        migrations.AddIndex(
            model_name='usageevent',
            index=models.Index(
                fields=['org_id', 'created_at'],
                name='usage_org_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='usageevent',
            index=models.Index(
                fields=['org_id', 'type', 'created_at'],
                name='usage_org_type_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='usageevent',
            index=models.Index(
                fields=['site_id', 'created_at'],
                name='usage_site_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='usageevent',
            index=models.Index(
                fields=['chatbot_id', 'created_at'],
                name='usage_chatbot_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='usageevent',
            index=models.Index(
                fields=['type', 'created_at'],
                name='usage_type_created_idx'
            ),
        ),

        # Quota indexes
        migrations.AddIndex(
            model_name='quota',
            index=models.Index(
                fields=['org_id', 'period_start'],
                name='quota_org_period_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='quota',
            index=models.Index(
                fields=['period_start', 'period_end'],
                name='quota_period_idx'
            ),
        ),
    ]
