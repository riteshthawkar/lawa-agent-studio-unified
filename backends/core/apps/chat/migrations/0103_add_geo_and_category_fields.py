# Generated manually for geo and category fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0102_remove_chatfeedback_chat_feedback_msg_created_idx_and_more'),
    ]

    operations = [
        # Add geo fields to ChatSession
        migrations.AddField(
            model_name='chatsession',
            name='geo_country_code',
            field=models.CharField(
                blank=True,
                help_text="ISO 3166-1 alpha-2 country code (e.g., 'US', 'AE')",
                max_length=2,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='chatsession',
            name='geo_country_name',
            field=models.CharField(
                blank=True,
                help_text='Full country name',
                max_length=100,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='chatsession',
            name='geo_region',
            field=models.CharField(
                blank=True,
                help_text='Region/state name',
                max_length=100,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='chatsession',
            name='geo_city',
            field=models.CharField(
                blank=True,
                help_text='City name (optional, for analytics)',
                max_length=100,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='chatsession',
            name='client_ip',
            field=models.GenericIPAddressField(
                blank=True,
                help_text='Client IP address (hashed for privacy in production)',
                null=True
            ),
        ),
        # Add geo indexes
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(fields=['geo_country_code'], name='chat_sessio_geo_country_idx'),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(fields=['geo_country_code', 'geo_region'], name='chat_sessio_geo_region_idx'),
        ),

        # Add query classification fields to ChatMessage
        migrations.AddField(
            model_name='chatmessage',
            name='query_category',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="LLM-classified query category (e.g., 'billing', 'support', 'product_info')",
                max_length=100,
                null=True
            ),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='query_category_confidence',
            field=models.FloatField(
                blank=True,
                help_text='Confidence score for the category classification (0.0 to 1.0)',
                null=True
            ),
        ),
        # Add category indexes
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(fields=['query_category'], name='chat_messag_category_idx'),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(fields=['query_category', 'created_at'], name='chat_messag_cat_created_idx'),
        ),
    ]
