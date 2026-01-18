"""
Test factories for creating realistic test data.

These factories generate data that mirrors real-world scenarios,
including edge cases and boundary conditions.
"""

import uuid
import random
from datetime import date, datetime, timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences
from apps.usage.models import Subscription

User = get_user_model()


class TestDataFactory:
    """
    Factory for creating complete test data sets.

    Provides realistic data that covers:
    - Normal use cases
    - Edge cases (empty values, max values)
    - Boundary conditions
    - Multi-tenant scenarios
    """

    # Real-world intent categories
    INTENTS = [
        'pricing_inquiry', 'demo_request', 'support_question',
        'feature_inquiry', 'integration_help', 'billing_issue',
        'technical_support', 'sales_inquiry', 'partnership',
        'cancellation', 'upgrade_request', 'feedback'
    ]

    # Real-world questions visitors ask
    SAMPLE_QUESTIONS = [
        "How much does this cost?",
        "Can I get a demo?",
        "What integrations do you support?",
        "How does billing work?",
        "Can I cancel anytime?",
        "Do you have an API?",
        "What's the difference between plans?",
        "How do I set up the chatbot?",
        "Can multiple team members use it?",
        "Is there a free trial?",
        "How secure is my data?",
        "Do you support multiple languages?",
    ]

    # Real-world geo locations
    GEO_LOCATIONS = [
        "San Francisco, CA, USA",
        "New York, NY, USA",
        "London, United Kingdom",
        "Berlin, Germany",
        "Tokyo, Japan",
        "Sydney, Australia",
        "Toronto, Canada",
        "Mumbai, India",
        "São Paulo, Brazil",
        None,  # Some sessions have no geo data
        "",    # Some have empty string
    ]

    DEVICE_TYPES = ['desktop', 'mobile', 'tablet', None]

    @classmethod
    def create_user(cls, email=None, **kwargs):
        """Create a verified user with realistic data."""
        uid = uuid.uuid4().hex[:8]
        email = email or f"testuser_{uid}@example.com"
        user = User.objects.create_user(
            username=kwargs.get('username', f"user_{uid}"),
            email=email,
            password=kwargs.get('password', 'TestPassword123!'),
            name=kwargs.get('name', f"Test User {uid}"),
        )
        user.is_active = True
        user.is_email_verified = True
        user.save()
        return user

    @classmethod
    def create_organization(cls, name=None, **kwargs):
        """Create an organization with realistic data."""
        uid = uuid.uuid4().hex[:8]
        return Organization.objects.create(
            name=name or f"Test Organization {uid}",
            slug=kwargs.get('slug', f"test-org-{uid}"),
            status=kwargs.get('status', 'active'),
        )

    @classmethod
    def create_membership(cls, user, org, role='owner'):
        """Create a membership linking user to organization."""
        return Membership.objects.create(
            user=user,
            organization=org,
            role=role
        )

    @classmethod
    def create_site(cls, org, domain=None, **kwargs):
        """Create a site with realistic data."""
        uid = uuid.uuid4().hex[:8]
        return Site.objects.create(
            org_id=org.id,
            domain=domain or f"https://test-site-{uid}.example.com",
            name=kwargs.get('name', f"Test Site {uid}"),
            status=kwargs.get('status', 'active'),
        )

    @classmethod
    def create_chatbot(cls, site, name=None, **kwargs):
        """Create a chatbot with realistic data."""
        uid = uuid.uuid4().hex[:8]
        return Chatbot.objects.create(
            site=site,
            name=name or f"Test Chatbot {uid}",
            status=kwargs.get('status', 'active'),
        )

    @classmethod
    def create_chat_session(cls, chatbot, **kwargs):
        """Create a chat session with realistic metadata."""
        return ChatSession.objects.create(
            chatbot=chatbot,
            session_id=kwargs.get('session_id', str(uuid.uuid4())),
            visitor_id=kwargs.get('visitor_id', str(uuid.uuid4())),
            ip_address=kwargs.get('ip_address', '192.168.1.100'),
            user_agent=kwargs.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
            referrer_url=kwargs.get('referrer_url', 'https://google.com'),
        )

    @classmethod
    def create_chat_messages(cls, session, count=5, include_feedback=False):
        """Create realistic chat messages for a session."""
        messages = []
        roles = ['user', 'assistant']

        for i in range(count):
            role = roles[i % 2]
            content = random.choice(cls.SAMPLE_QUESTIONS) if role == 'user' else "Thank you for your question. Here's how I can help..."

            feedback = None
            if include_feedback and role == 'assistant' and random.random() > 0.7:
                feedback = random.choice(['like', 'dislike'])

            msg = ChatMessage.objects.create(
                session=session,
                role=role,
                content=content,
                feedback=feedback,
            )
            messages.append(msg)

        return messages

    @classmethod
    def create_lead_score(
        cls,
        session,
        chatbot,
        org_id,
        priority='cold',
        total_score=None,
        session_date=None,
        **kwargs
    ):
        """
        Create a lead score with realistic data.

        Handles score calculation to ensure consistency:
        - hot: 70-100
        - warm: 40-69
        - cold: 0-39
        """
        # Calculate realistic scores based on priority
        if total_score is None:
            if priority == 'hot':
                total_score = random.randint(70, 100)
            elif priority == 'warm':
                total_score = random.randint(40, 69)
            else:
                total_score = random.randint(0, 39)

        # Split into engagement and intent scores
        engagement_score = total_score // 2
        intent_score = total_score - engagement_score

        session_date = session_date or date.today() - timedelta(days=random.randint(0, 30))

        return LeadScore.objects.create(
            session=session,
            chatbot=chatbot,
            org_id=org_id,
            engagement_score=engagement_score,
            intent_score=intent_score,
            total_score=total_score,
            priority=priority,
            detected_intent=kwargs.get('detected_intent', random.choice(cls.INTENTS)),
            key_questions=kwargs.get('key_questions', random.sample(cls.SAMPLE_QUESTIONS, 3)),
            conversation_summary=kwargs.get('conversation_summary', f"Visitor inquired about product features and pricing."),
            source_url=kwargs.get('source_url', f"https://example.com/pricing"),
            geo_location=kwargs.get('geo_location', random.choice(cls.GEO_LOCATIONS)),
            device_type=kwargs.get('device_type', random.choice(cls.DEVICE_TYPES)),
            session_date=session_date,
            session_duration_seconds=kwargs.get('session_duration_seconds', random.randint(60, 600)),
            message_count=kwargs.get('message_count', random.randint(3, 20)),
            had_positive_feedback=kwargs.get('had_positive_feedback', random.choice([True, False])),
            had_negative_feedback=kwargs.get('had_negative_feedback', random.choice([True, False])),
            llm_insights=kwargs.get('llm_insights', cls._generate_llm_insights(priority)),
        )

    @classmethod
    def _generate_llm_insights(cls, priority):
        """Generate realistic LLM insights based on priority."""
        if priority == 'hot':
            return {
                "analyzed_by_llm": True,
                "model_used": "gpt-4o-mini",
                "intent": {
                    "primary": "pricing_inquiry",
                    "confidence": 92,
                    "buying_signals": ["asked about pricing", "mentioned timeline", "requested demo"],
                    "objections": []
                },
                "entities": {
                    "company_name": "Acme Corporation",
                    "job_title": "VP Engineering",
                    "team_size": "50-100",
                    "industry": "SaaS",
                    "budget_signals": "Q1 budget approved",
                    "timeline": "next 2 weeks",
                    "use_case": "customer support automation"
                },
                "sentiment": "positive",
                "urgency": "high",
                "engagement_quality": "high",
                "competitor_mentions": ["Intercom"],
                "recommendations": {
                    "follow_up_action": "Schedule demo call ASAP",
                    "talking_points": ["ROI calculator", "implementation timeline"],
                    "content_gaps": []
                },
                "reasoning": "High intent signals with clear timeline and budget. Decision maker engaged."
            }
        elif priority == 'warm':
            return {
                "analyzed_by_llm": True,
                "model_used": "gpt-4o-mini",
                "intent": {
                    "primary": "feature_inquiry",
                    "confidence": 75,
                    "buying_signals": ["asked about features"],
                    "objections": ["budget concerns"]
                },
                "entities": {
                    "company_name": None,
                    "job_title": None,
                    "team_size": "10-50",
                    "industry": None,
                    "use_case": "general inquiry"
                },
                "sentiment": "neutral",
                "urgency": "medium",
                "engagement_quality": "medium",
                "recommendations": {
                    "follow_up_action": "Send comparison guide",
                    "talking_points": ["competitive pricing", "flexible plans"],
                    "content_gaps": ["pricing page"]
                },
                "reasoning": "Exploring options but no clear timeline."
            }
        else:
            return {
                "analyzed_by_llm": True,
                "model_used": "gpt-4o-mini",
                "intent": {
                    "primary": "support_question",
                    "confidence": 60,
                    "buying_signals": [],
                    "objections": []
                },
                "sentiment": "neutral",
                "urgency": "low",
                "engagement_quality": "low",
                "recommendations": {
                    "follow_up_action": "Add to newsletter",
                    "content_gaps": ["documentation"]
                },
                "reasoning": "General support inquiry, low buying intent."
            }

    @classmethod
    def create_weekly_report(
        cls,
        org,
        user,
        chatbot=None,
        week_start=None,
        **kwargs
    ):
        """Create a weekly report with realistic aggregate data."""
        week_start = week_start or (date.today() - timedelta(days=date.today().weekday() + 7))
        week_end = week_start + timedelta(days=6)

        total_leads = kwargs.get('total_leads', random.randint(10, 100))
        hot_leads = int(total_leads * 0.15)
        warm_leads = int(total_leads * 0.35)
        cold_leads = total_leads - hot_leads - warm_leads

        return WeeklyLeadsReport.objects.create(
            org=org,
            user=user,
            chatbot=chatbot,
            week_start=week_start,
            week_end=week_end,
            total_sessions=kwargs.get('total_sessions', total_leads * 2),
            total_leads=total_leads,
            hot_leads=hot_leads,
            warm_leads=warm_leads,
            cold_leads=cold_leads,
            leads_change_percent=kwargs.get('leads_change_percent', random.uniform(-20, 50)),
            sessions_change_percent=kwargs.get('sessions_change_percent', random.uniform(-10, 30)),
            report_data=kwargs.get('report_data', cls._generate_report_data(total_leads)),
            email_sent=kwargs.get('email_sent', False),
        )

    @classmethod
    def _generate_report_data(cls, total_leads):
        """Generate realistic report data JSON."""
        return {
            "top_leads": [
                {
                    "id": str(uuid.uuid4()),
                    "priority": random.choice(['hot', 'warm', 'cold']),
                    "score": random.randint(40, 95),
                    "intent": random.choice(cls.INTENTS),
                    "questions": random.sample(cls.SAMPLE_QUESTIONS, 2),
                    "geo": random.choice([g for g in cls.GEO_LOCATIONS if g]),
                    "device": random.choice([d for d in cls.DEVICE_TYPES if d]),
                    "date": (date.today() - timedelta(days=random.randint(1, 7))).isoformat(),
                }
                for _ in range(min(5, total_leads))
            ],
            "intent_breakdown": {
                intent: random.randint(1, 20)
                for intent in random.sample(cls.INTENTS, 5)
            },
            "geo_distribution": {
                "United States": random.randint(20, 50),
                "United Kingdom": random.randint(10, 25),
                "Germany": random.randint(5, 15),
                "Canada": random.randint(5, 10),
            },
            "device_breakdown": {
                "desktop": random.randint(40, 60),
                "mobile": random.randint(30, 45),
                "tablet": random.randint(5, 15),
            },
            "daily_trend": [
                {"date": (date.today() - timedelta(days=i)).isoformat(), "count": random.randint(5, 20)}
                for i in range(7)
            ],
            "top_questions": random.sample(cls.SAMPLE_QUESTIONS, 5),
            "avg_session_duration": random.randint(120, 360),
            "avg_messages_per_session": round(random.uniform(3.5, 8.0), 1),
            "feedback_summary": {
                "positive": random.randint(10, 30),
                "negative": random.randint(2, 10),
                "none": random.randint(50, 80),
            }
        }

    @classmethod
    def create_subscription(cls, org, plan='basic', **kwargs):
        """Create a subscription for an organization."""
        return Subscription.objects.create(
            organization=org,
            plan=plan,
            status=kwargs.get('status', 'active'),
            trial_ends_at=kwargs.get('trial_ends_at'),
            analytics_retention_days=kwargs.get('analytics_retention_days'),
            features_override=kwargs.get('features_override', {}),
        )

    @classmethod
    def create_report_preferences(cls, user, org, **kwargs):
        """Create report preferences for a user."""
        return ReportPreferences.objects.create(
            user=user,
            org=org,
            weekly_report_enabled=kwargs.get('weekly_report_enabled', True),
            report_day=kwargs.get('report_day', 0),  # Monday
            report_hour=kwargs.get('report_hour', 9),
            timezone=kwargs.get('timezone', 'UTC'),
            notify_hot_leads_immediately=kwargs.get('notify_hot_leads_immediately', False),
        )

    @classmethod
    def create_complete_test_setup(cls, plan='basic'):
        """
        Create a complete test environment with all related objects.

        Returns a dict with all created objects for easy access in tests.
        """
        user = cls.create_user()
        org = cls.create_organization()
        membership = cls.create_membership(user, org)
        site = cls.create_site(org)
        chatbot = cls.create_chatbot(site)
        subscription = cls.create_subscription(org, plan)

        # Create multiple lead scores with different priorities
        leads = []
        for priority in ['hot', 'hot', 'warm', 'warm', 'warm', 'cold', 'cold', 'cold', 'cold', 'cold']:
            session = cls.create_chat_session(chatbot)
            cls.create_chat_messages(session, count=random.randint(4, 12), include_feedback=True)
            lead = cls.create_lead_score(session, chatbot, org.id, priority=priority)
            leads.append(lead)

        return {
            'user': user,
            'org': org,
            'membership': membership,
            'site': site,
            'chatbot': chatbot,
            'subscription': subscription,
            'leads': leads,
        }
