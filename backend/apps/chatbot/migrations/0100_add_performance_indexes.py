"""
Add performance indexes for chatbot models.

This migration adds missing composite and single-column indexes
to improve query performance for common access patterns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0005_chatbot_config'),
    ]

    operations = [
        # Chatbot indexes
        migrations.AddIndex(
            model_name='chatbot',
            index=models.Index(
                fields=['site_id', 'status'],
                name='chatbot_site_status_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatbot',
            index=models.Index(
                fields=['site_id', 'created_at'],
                name='chatbot_site_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatbot',
            index=models.Index(
                fields=['status', 'created_at'],
                name='chatbot_status_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatbot',
            index=models.Index(
                fields=['api_key'],
                name='chatbot_api_key_idx'
            ),
        ),

        # Partial index for active chatbots (frequently queried)
        migrations.AddIndex(
            model_name='chatbot',
            index=models.Index(
                fields=['site_id', 'created_at'],
                name='chatbot_active_site_created_idx',
                condition=models.Q(status='active')
            ),
        ),
    ]
