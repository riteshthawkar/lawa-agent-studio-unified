# Generated manually for query category model

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0104_add_conversation_starter'),
    ]

    operations = [
        migrations.CreateModel(
            name='QueryCategory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chatbot', models.ForeignKey(
                    help_text='The chatbot this category belongs to',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='query_categories',
                    to='chatbot.chatbot'
                )),
                ('name', models.CharField(
                    help_text="Category name (e.g., 'Billing', 'Technical Support', 'Product Info')",
                    max_length=100
                )),
                ('description', models.TextField(
                    blank=True,
                    default='',
                    help_text='Description to help the AI classify queries into this category'
                )),
                ('keywords', models.JSONField(
                    blank=True,
                    default=list,
                    help_text='List of keywords/phrases that indicate this category'
                )),
                ('color', models.CharField(
                    default='#6366f1',
                    help_text='Color for displaying this category in analytics (hex format)',
                    max_length=7
                )),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='Whether this category is currently active for classification'
                )),
                ('display_order', models.PositiveIntegerField(
                    default=0,
                    help_text='Display order in UI (lower numbers appear first)'
                )),
            ],
            options={
                'verbose_name': 'Query Category',
                'verbose_name_plural': 'Query Categories',
                'db_table': 'query_categories',
                'ordering': ['display_order', 'name'],
            },
        ),
        migrations.AddIndex(
            model_name='querycategory',
            index=models.Index(fields=['chatbot', 'is_active'], name='query_categ_chatbot_active_idx'),
        ),
        migrations.AddIndex(
            model_name='querycategory',
            index=models.Index(fields=['display_order'], name='query_categ_display_order_idx'),
        ),
        migrations.AddConstraint(
            model_name='querycategory',
            constraint=models.UniqueConstraint(
                fields=['chatbot', 'name'],
                name='unique_category_name_per_chatbot'
            ),
        ),
    ]
