"""
Add performance indexes for chat models.

This migration adds missing composite and single-column indexes
to improve query performance for common access patterns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0004_remove_chatsession_chat_sessio_chatbot_15800d_idx_and_more'),
    ]

    operations = [
        # ChatSession indexes
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['org_id', 'status'],
                name='chat_sess_org_status_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['org_id', 'created_at'],
                name='chat_sess_org_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['chatbot_id', 'created_at'],
                name='chat_sess_bot_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['site_id', 'created_at'],
                name='chat_sess_site_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['user_id', 'created_at'],
                name='chat_sess_user_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['status', 'last_activity'],
                name='chat_sess_status_activity_idx'
            ),
        ),

        # ChatMessage indexes
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(
                fields=['session', 'created_at'],
                name='chat_msg_sess_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(
                fields=['session', 'role', 'created_at'],
                name='chat_msg_sess_role_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(
                fields=['created_at'],
                name='chat_msg_created_idx'
            ),
        ),

        # ChatFeedback indexes
        migrations.AddIndex(
            model_name='chatfeedback',
            index=models.Index(
                fields=['message', 'created_at'],
                name='chat_feedback_msg_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatfeedback',
            index=models.Index(
                fields=['message', 'user_id', 'created_at'],
                name='chat_feedback_msg_user_created_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='chatfeedback',
            index=models.Index(
                fields=['feedback_type', 'created_at'],
                name='chat_feedback_type_created_idx'
            ),
        ),
    ]
