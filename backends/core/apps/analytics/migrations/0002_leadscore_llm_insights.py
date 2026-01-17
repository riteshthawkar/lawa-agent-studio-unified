# Generated migration for adding llm_insights field to LeadScore

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='leadscore',
            name='llm_insights',
            field=models.JSONField(
                blank=True,
                help_text='\n        LLM-extracted insights structure:\n        {\n            "analyzed_by_llm": true,\n            "model_used": "gpt-4o-mini",\n            "intent": {\n                "primary": "pricing_inquiry",\n                "confidence": 85,\n                "buying_signals": ["asked about pricing", "mentioned timeline"],\n                "objections": ["budget concerns"]\n            },\n            "entities": {\n                "company_name": "Acme Inc",\n                "job_title": "CTO",\n                "team_size": "50-100",\n                "industry": "SaaS",\n                "budget_signals": "mentioned Q1 budget",\n                "timeline": "next month",\n                "use_case": "customer support automation"\n            },\n            "sentiment": "positive",\n            "urgency": "high",\n            "engagement_quality": "high",\n            "competitor_mentions": ["Intercom", "Zendesk"],\n            "recommendations": {\n                "follow_up_action": "Schedule demo call",\n                "talking_points": ["ROI calculator", "implementation timeline"],\n                "content_gaps": ["pricing page", "case studies"]\n            },\n            "reasoning": "High intent signals with clear timeline and budget"\n        }\n        ',
                null=True,
            ),
        ),
    ]
