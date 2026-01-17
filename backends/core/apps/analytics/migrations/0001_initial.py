# Generated migration for analytics app

import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organizations', '0001_initial'),
        ('chatbot', '0001_create_chatbot_model'),
        ('chat', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeadScore',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('org_id', models.UUIDField(db_index=True, help_text='Organization ID for multi-tenancy filtering')),
                ('engagement_score', models.IntegerField(default=0, help_text='Score based on engagement signals (messages, duration, feedback)')),
                ('intent_score', models.IntegerField(default=0, help_text='Score based on high-intent keywords detected')),
                ('total_score', models.IntegerField(db_index=True, default=0, help_text='Combined score (engagement + intent)')),
                ('priority', models.CharField(choices=[('hot', 'Hot'), ('warm', 'Warm'), ('cold', 'Cold')], db_index=True, default='cold', help_text='Lead priority classification based on total score', max_length=10)),
                ('detected_intent', models.CharField(blank=True, db_index=True, help_text='Primary detected intent (pricing, demo, contact, support, etc.)', max_length=100, null=True)),
                ('key_questions', models.JSONField(blank=True, default=list, help_text='List of important questions asked by the visitor')),
                ('conversation_summary', models.TextField(blank=True, default='', help_text='Brief summary of the conversation')),
                ('source_url', models.URLField(blank=True, help_text='Referrer URL where the conversation started', max_length=500, null=True)),
                ('geo_location', models.CharField(blank=True, help_text='Geographic location (city, country)', max_length=200, null=True)),
                ('device_type', models.CharField(blank=True, help_text='Device type (mobile, tablet, desktop)', max_length=20, null=True)),
                ('session_date', models.DateField(db_index=True, help_text='Date of the session (for date-range queries)')),
                ('session_duration_seconds', models.IntegerField(default=0, help_text='Duration of the session in seconds')),
                ('message_count', models.IntegerField(default=0, help_text='Total number of messages in the session')),
                ('had_positive_feedback', models.BooleanField(default=False, help_text='Whether the session had any positive feedback (likes)')),
                ('had_negative_feedback', models.BooleanField(default=False, help_text='Whether the session had any negative feedback (dislikes)')),
                ('chatbot', models.ForeignKey(help_text='The chatbot that handled this conversation', on_delete=django.db.models.deletion.CASCADE, related_name='lead_scores', to='chatbot.chatbot')),
                ('session', models.OneToOneField(help_text='The chat session this lead score is derived from', on_delete=django.db.models.deletion.CASCADE, related_name='lead_score', to='chat.chatsession')),
            ],
            options={
                'verbose_name': 'Lead Score',
                'verbose_name_plural': 'Lead Scores',
                'db_table': 'lead_scores',
                'ordering': ['-total_score', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='WeeklyLeadsReport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('week_start', models.DateField(db_index=True, help_text='Start date of the report week (Monday)')),
                ('week_end', models.DateField(help_text='End date of the report week (Sunday)')),
                ('total_sessions', models.IntegerField(default=0, help_text='Total chat sessions during the period')),
                ('total_leads', models.IntegerField(default=0, help_text='Total leads identified (all priorities)')),
                ('hot_leads', models.IntegerField(default=0, help_text='Number of hot (high priority) leads')),
                ('warm_leads', models.IntegerField(default=0, help_text='Number of warm (medium priority) leads')),
                ('cold_leads', models.IntegerField(default=0, help_text='Number of cold (low priority) leads')),
                ('leads_change_percent', models.FloatField(default=0, help_text='Percentage change in leads vs previous week')),
                ('sessions_change_percent', models.FloatField(default=0, help_text='Percentage change in sessions vs previous week')),
                ('report_data', models.JSONField(blank=True, default=dict, help_text='Detailed report data structure')),
                ('email_sent', models.BooleanField(default=False, help_text='Whether the email report has been sent')),
                ('email_sent_at', models.DateTimeField(blank=True, help_text='Timestamp when email was sent', null=True)),
                ('email_error', models.TextField(blank=True, default='', help_text='Error message if email sending failed')),
                ('chatbot', models.ForeignKey(blank=True, help_text='Specific chatbot for this report (null = all chatbots)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='weekly_leads_reports', to='chatbot.chatbot')),
                ('org', models.ForeignKey(help_text='Organization this report belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='weekly_leads_reports', to='organizations.organization')),
                ('user', models.ForeignKey(help_text='User who receives this report', on_delete=django.db.models.deletion.CASCADE, related_name='weekly_leads_reports', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Weekly Leads Report',
                'verbose_name_plural': 'Weekly Leads Reports',
                'db_table': 'weekly_leads_reports',
                'ordering': ['-week_start'],
            },
        ),
        migrations.CreateModel(
            name='ReportPreferences',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('weekly_report_enabled', models.BooleanField(default=True, help_text='Whether to send weekly email reports')),
                ('report_day', models.IntegerField(choices=[(0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')], default=0, help_text='Day of week to send reports (0=Monday)')),
                ('report_hour', models.IntegerField(default=9, help_text="Hour of day to send reports (0-23, in user's timezone)")),
                ('timezone', models.CharField(default='UTC', help_text="User's timezone for report scheduling", max_length=50)),
                ('include_chatbot_ids', models.JSONField(blank=True, default=list, help_text='List of chatbot IDs to include (empty = all chatbots)')),
                ('min_lead_score', models.IntegerField(default=0, help_text='Minimum lead score to include in reports')),
                ('include_cold_leads', models.BooleanField(default=True, help_text='Whether to include cold leads in reports')),
                ('notify_hot_leads_immediately', models.BooleanField(default=False, help_text='Send immediate notification for hot leads')),
                ('daily_summary_enabled', models.BooleanField(default=False, help_text='Send daily summary in addition to weekly report')),
                ('org', models.ForeignKey(help_text='Organization context for these preferences', on_delete=django.db.models.deletion.CASCADE, related_name='report_preferences', to='organizations.organization')),
                ('user', models.ForeignKey(help_text='User these preferences belong to', on_delete=django.db.models.deletion.CASCADE, related_name='report_preferences', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Report Preferences',
                'verbose_name_plural': 'Report Preferences',
                'db_table': 'report_preferences',
            },
        ),
        # Add indexes
        migrations.AddIndex(
            model_name='leadscore',
            index=models.Index(fields=['org_id', 'session_date'], name='lead_scores_org_id_session_idx'),
        ),
        migrations.AddIndex(
            model_name='leadscore',
            index=models.Index(fields=['org_id', 'priority'], name='lead_scores_org_id_priority_idx'),
        ),
        migrations.AddIndex(
            model_name='leadscore',
            index=models.Index(fields=['chatbot', 'session_date'], name='lead_scores_chatbot_date_idx'),
        ),
        migrations.AddIndex(
            model_name='leadscore',
            index=models.Index(fields=['detected_intent'], name='lead_scores_intent_idx'),
        ),
        migrations.AddIndex(
            model_name='leadscore',
            index=models.Index(fields=['-total_score'], name='lead_scores_total_score_idx'),
        ),
        migrations.AddIndex(
            model_name='leadscore',
            index=models.Index(fields=['session_date', '-total_score'], name='lead_scores_date_score_idx'),
        ),
        migrations.AddIndex(
            model_name='weeklyleadsreport',
            index=models.Index(fields=['org', 'week_start'], name='weekly_reports_org_week_idx'),
        ),
        migrations.AddIndex(
            model_name='weeklyleadsreport',
            index=models.Index(fields=['user', 'week_start'], name='weekly_reports_user_week_idx'),
        ),
        migrations.AddIndex(
            model_name='weeklyleadsreport',
            index=models.Index(fields=['email_sent'], name='weekly_reports_email_sent_idx'),
        ),
        migrations.AddIndex(
            model_name='reportpreferences',
            index=models.Index(fields=['weekly_report_enabled'], name='report_prefs_enabled_idx'),
        ),
        migrations.AddIndex(
            model_name='reportpreferences',
            index=models.Index(fields=['report_day', 'report_hour'], name='report_prefs_schedule_idx'),
        ),
        # Add constraints
        migrations.AddConstraint(
            model_name='weeklyleadsreport',
            constraint=models.UniqueConstraint(fields=['org', 'user', 'chatbot', 'week_start'], name='unique_weekly_report_per_user_chatbot'),
        ),
        migrations.AddConstraint(
            model_name='reportpreferences',
            constraint=models.UniqueConstraint(fields=['user', 'org'], name='unique_preferences_per_user_org'),
        ),
    ]
