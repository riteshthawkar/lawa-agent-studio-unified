"""
Management command to populate realistic demo data for investor presentations.

This command creates comprehensive demo data including:
- Sites (knowledge bases) with indexed pages
- Chatbots with conversation starters and query categories
- Chat sessions with realistic conversations
- Chat feedback (positive and negative)
- Lead scores with various priorities
- Usage events for analytics
- Indexing jobs and indexed pages

Usage:
    python manage.py populate_demo_data --email=prashantthawkar172003@gmail.com
"""

import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from apps.auth.models import User
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot, QueryCategory, ConversationStarter
from apps.chat.models import ChatSession, ChatMessage, ChatFeedback
from apps.analytics.models import LeadScore, WeeklyLeadsReport, ReportPreferences
from apps.usage.models import UsageEvent, Subscription
from apps.indexing.models import IndexingJob, IndexedPage


class Command(BaseCommand):
    help = 'Populate realistic demo data for investor presentation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            default='prashantthawkar172003@gmail.com',
            help='Email of the user to add demo data for'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing demo data before creating new data'
        )

    def handle(self, *args, **options):
        email = options['email']
        clear = options['clear']

        self.stdout.write(f"Looking up user: {email}")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"User with email '{email}' not found."))
            return

        # Get or create organization for user
        membership = Membership.objects.filter(user=user).first()
        if not membership:
            self.stderr.write(self.style.ERROR(f"User has no organization membership."))
            return

        org = membership.organization
        self.stdout.write(f"Using organization: {org.name} (ID: {org.id})")

        if clear:
            self.stdout.write("Clearing existing demo data...")
            self._clear_demo_data(org)

        with transaction.atomic():
            self._create_demo_data(user, org)

        self.stdout.write(self.style.SUCCESS("Demo data populated successfully!"))

    def _clear_demo_data(self, org):
        """Clear existing demo data for organization"""
        # Clear in dependency order (reverse)
        ChatFeedback.objects.filter(message__session__chatbot__site__org_id=org.id).delete()
        ChatMessage.objects.filter(session__chatbot__site__org_id=org.id).delete()
        ChatSession.objects.filter(chatbot__site__org_id=org.id).delete()
        LeadScore.objects.filter(org_id=org.id).delete()
        WeeklyLeadsReport.objects.filter(org=org).delete()
        ConversationStarter.objects.filter(chatbot__site__org_id=org.id).delete()
        QueryCategory.objects.filter(chatbot__site__org_id=org.id).delete()
        UsageEvent.objects.filter(org_id=org.id).delete()
        IndexedPage.objects.filter(org_id=org.id).delete()
        IndexingJob.objects.filter(org_id=org.id).delete()
        Chatbot.objects.filter(site__org_id=org.id).delete()
        Site.objects.filter(org_id=org.id).delete()
        self.stdout.write("Cleared existing data.")

    def _create_demo_data(self, user, org):
        """Create comprehensive demo data"""
        now = timezone.now()

        # Upgrade organization to premium for demo
        org.plan_tier = 'premium'
        org.save()

        # Create or update subscription
        subscription, _ = Subscription.objects.update_or_create(
            organization=org,
            defaults={
                'plan': 'premium',
                'status': 'active',
                'current_period_start': now - timedelta(days=15),
                'current_period_end': now + timedelta(days=15),
            }
        )
        self.stdout.write("  ✓ Premium subscription activated")

        # Create demo sites (knowledge bases)
        sites_data = [
            {
                'name': 'TechCorp Documentation',
                'domain': 'docs.techcorp.io',
                'pages': 156,
                'documents': 1250,
            },
            {
                'name': 'E-Commerce Help Center',
                'domain': 'help.shopease.com',
                'pages': 89,
                'documents': 720,
            },
            {
                'name': 'SaaS Product Guide',
                'domain': 'guide.cloudapp.co',
                'pages': 234,
                'documents': 1890,
            },
        ]

        created_sites = []
        for site_data in sites_data:
            site = Site.objects.create(
                name=site_data['name'],
                domain=site_data['domain'],
                status='active',
                org_id=org.id,
                indexed_pages_count=site_data['pages'],
                total_documents=site_data['documents'],
                last_indexed_at=now - timedelta(hours=random.randint(2, 48)),
                max_pages=500,
                active_namespace=f"site_{uuid.uuid4().hex[:8]}_{int(now.timestamp())}",
            )
            created_sites.append(site)
            self._create_indexing_data(site, org, site_data['pages'])
            self.stdout.write(f"  ✓ Site created: {site.name}")

        # Create chatbots for each site
        chatbot_configs = [
            {
                'name': 'TechCorp Assistant',
                'welcome_message': 'Hello! I\'m your TechCorp documentation assistant. How can I help you today?',
                'primary_color': '#3B82F6',
            },
            {
                'name': 'ShopEase Support Bot',
                'welcome_message': 'Welcome to ShopEase! I can help you with orders, returns, and product questions.',
                'primary_color': '#10B981',
            },
            {
                'name': 'CloudApp Guide',
                'welcome_message': 'Hi there! Need help with CloudApp? I\'m here to assist with setup, features, and troubleshooting.',
                'primary_color': '#8B5CF6',
            },
        ]

        created_chatbots = []
        for i, (site, config) in enumerate(zip(created_sites, chatbot_configs)):
            chatbot = Chatbot.objects.create(
                site=site,
                name=config['name'],
                greeting_message=config['welcome_message'],
                primary_color=config['primary_color'],
                status='active',
            )
            created_chatbots.append(chatbot)
            self._create_chatbot_config(chatbot)
            self.stdout.write(f"  ✓ Chatbot created: {chatbot.name}")

        # Create chat sessions and messages
        total_sessions = 0
        total_messages = 0
        for chatbot in created_chatbots:
            sessions, messages = self._create_chat_sessions(chatbot, org, user)
            total_sessions += sessions
            total_messages += messages

        self.stdout.write(f"  ✓ Created {total_sessions} sessions with {total_messages} messages")

        # Create lead scores
        leads_created = self._create_lead_scores(created_chatbots, org)
        self.stdout.write(f"  ✓ Created {leads_created} lead scores")

        # Create weekly reports
        self._create_weekly_reports(user, org, created_chatbots)
        self.stdout.write("  ✓ Created weekly reports")

        # Create usage events for analytics
        self._create_usage_events(org, created_sites, created_chatbots)
        self.stdout.write("  ✓ Created usage events")

        # Create report preferences
        ReportPreferences.objects.update_or_create(
            user=user,
            org=org,
            defaults={
                'weekly_report_enabled': True,
                'report_day': 1,  # Monday
                'report_hour': 9,
            }
        )
        self.stdout.write("  ✓ Report preferences configured")

    def _create_indexing_data(self, site, org, page_count):
        """Create indexing jobs and indexed pages"""
        now = timezone.now()

        # Create completed indexing job
        job = IndexingJob.objects.create(
            site_id=site.id,
            org_id=org.id,
            status='completed',
            max_pages=500,
            urls_collected=page_count,
            urls_processed=page_count,
            pages_indexed=page_count,
            documents_indexed=site.total_documents,
            started_at=now - timedelta(hours=3),
            completed_at=now - timedelta(hours=2),
            external_job_id=f"demo_{uuid.uuid4().hex}",
        )

        # Create some indexed pages
        sample_paths = [
            '/docs/getting-started',
            '/docs/installation',
            '/docs/configuration',
            '/docs/api-reference',
            '/docs/tutorials/beginner',
            '/docs/tutorials/advanced',
            '/docs/faq',
            '/docs/troubleshooting',
            '/docs/changelog',
            '/docs/pricing',
        ]

        for path in sample_paths[:min(10, page_count)]:
            IndexedPage.objects.create(
                site_id=site.id,
                org_id=org.id,
                indexing_job_id=job.id,
                url=f"https://{site.domain}{path}",
                status='indexed',
                document_count=random.randint(3, 15),
                content_size_bytes=random.randint(5000, 50000),
                processed_at=now - timedelta(hours=2),
            )

    def _create_chatbot_config(self, chatbot):
        """Create query categories and conversation starters"""
        # Query categories
        categories = [
            ('Product Info', 'Questions about product features and capabilities', '#3B82F6'),
            ('Pricing', 'Questions about pricing, plans, and billing', '#10B981'),
            ('Technical Support', 'Technical issues and troubleshooting', '#F59E0B'),
            ('Getting Started', 'Onboarding and setup questions', '#8B5CF6'),
            ('Integration', 'API and integration questions', '#EC4899'),
        ]

        for i, (name, desc, color) in enumerate(categories):
            QueryCategory.objects.create(
                chatbot=chatbot,
                name=name,
                description=desc,
                color=color,
                display_order=i,
                is_active=True,
            )

        # Conversation starters
        starters = [
            'How do I get started?',
            'What are the pricing plans?',
            'How do I integrate with my website?',
            'Can you help me troubleshoot an issue?',
        ]

        for i, text in enumerate(starters):
            ConversationStarter.objects.create(
                chatbot=chatbot,
                question=text,
                display_order=i,
                is_active=True,
                click_count=random.randint(5, 50),
            )

    def _create_chat_sessions(self, chatbot, org, user):
        """Create realistic chat sessions with messages"""
        now = timezone.now()
        sessions_created = 0
        messages_created = 0

        # Sample conversations
        conversations = [
            {
                'visitor_name': 'John Smith',
                'visitor_email': 'john.smith@company.com',
                'messages': [
                    ('user', 'Hi, I\'m interested in your enterprise plan. What features are included?'),
                    ('assistant', 'Hello John! Great question. Our Enterprise plan includes unlimited chatbots, priority support, custom integrations, advanced analytics, and dedicated account management. Would you like me to explain any specific feature in detail?'),
                    ('user', 'Yes, can you tell me more about the custom integrations?'),
                    ('assistant', 'Absolutely! Custom integrations allow you to connect our platform with your existing tools like Salesforce, HubSpot, Zendesk, and more. We also provide API access for building custom workflows. Our team can help you set up these integrations during onboarding.'),
                    ('user', 'That sounds perfect. How do I schedule a demo?'),
                    ('assistant', 'I\'d be happy to help you schedule a demo! You can book directly at calendly.com/lawa-demo or I can have our sales team reach out to you. Which would you prefer?'),
                ],
                'feedback': 'positive',
                'category': 'Pricing',
            },
            {
                'visitor_name': 'Sarah Johnson',
                'visitor_email': 'sarah@startup.io',
                'messages': [
                    ('user', 'I need help setting up my first chatbot'),
                    ('assistant', 'Welcome! I\'d be glad to help you get started. First, you\'ll need to add your website as a knowledge base. Have you already done that?'),
                    ('user', 'Not yet, how do I do that?'),
                    ('assistant', 'It\'s easy! Go to the Dashboard, click "New Project", enter your website URL, and click "Start Indexing". Our system will automatically crawl your site and build a knowledge base. This usually takes 5-15 minutes depending on your site size.'),
                    ('user', 'Got it, thanks! The indexing just finished. What\'s next?'),
                    ('assistant', 'Perfect! Now go to the Chatbots section and click "Create Chatbot". Select your knowledge base, customize the appearance, and you\'ll get an embed code to add to your website. Would you like a step-by-step walkthrough?'),
                ],
                'feedback': 'positive',
                'category': 'Getting Started',
            },
            {
                'visitor_name': None,
                'visitor_email': None,
                'messages': [
                    ('user', 'What programming languages do you support for the API?'),
                    ('assistant', 'Our API is language-agnostic and works with any language that can make HTTP requests. We provide official SDKs for JavaScript/TypeScript, Python, and Ruby. For other languages, you can use our REST API directly with comprehensive documentation available at docs.lawa.io/api.'),
                    ('user', 'Do you have webhooks for real-time updates?'),
                    ('assistant', 'Yes! We support webhooks for various events including new conversations, feedback received, and indexing completed. You can configure webhooks in Settings > Integrations. Each webhook includes a signature for security verification.'),
                ],
                'feedback': None,
                'category': 'Integration',
            },
            {
                'visitor_name': 'Mike Chen',
                'visitor_email': 'mike@techfirm.com',
                'messages': [
                    ('user', 'The chatbot is giving wrong answers about our pricing'),
                    ('assistant', 'I apologize for the confusion. This usually happens when the pricing page wasn\'t indexed correctly or has been updated since the last indexing. Let me help you fix this.'),
                    ('user', 'How do I update the knowledge base?'),
                    ('assistant', 'You can re-index your site by going to your Project, clicking the "Re-index" button. This will crawl your site again and update all the information. You can also manually add or edit specific content in the Knowledge Base section.'),
                    ('user', 'I just re-indexed. How long until the changes take effect?'),
                    ('assistant', 'The changes should be live immediately after indexing completes. You can verify by testing a question about your pricing. If you\'re still seeing incorrect information, try clearing your browser cache or testing in an incognito window.'),
                ],
                'feedback': 'positive',
                'category': 'Technical Support',
            },
            {
                'visitor_name': 'Emily Davis',
                'visitor_email': 'emily@agency.co',
                'messages': [
                    ('user', 'Can I white-label the chatbot for my clients?'),
                    ('assistant', 'Yes! White-labeling is available on our Premium and Enterprise plans. You can customize the chatbot name, colors, logo, and remove Lawa branding entirely. Enterprise customers also get custom domain support for the widget.'),
                    ('user', 'Perfect! We manage 20+ client websites. Is there a bulk discount?'),
                    ('assistant', 'Absolutely! For agencies managing multiple clients, we offer volume discounts and a partner program with additional benefits. I\'d recommend speaking with our partnerships team. Would you like me to arrange a call?'),
                    ('user', 'Yes please, that would be great'),
                    ('assistant', 'Excellent! I\'ll have our partnerships team reach out to you at emily@agency.co within 24 hours. In the meantime, you can learn more about our partner program at lawa.io/partners. Is there anything else I can help you with?'),
                ],
                'feedback': 'positive',
                'category': 'Pricing',
            },
        ]

        # Create sessions spread over the last 60 days for realistic timeline
        for i, conv in enumerate(conversations):
            # Spread conversations evenly across 60 days 
            days_ago = random.randint(i * 10, min((i + 1) * 12, 60))
            # Uniform hour distribution across all hours (0-23) for uniform weekly chart
            hours_offset = random.randint(0, 23)
            # Use timedelta to set exact offset from now
            session_time = now - timedelta(days=days_ago, hours=hours_offset, minutes=random.randint(0, 59))
            
            # Generate random client IP for visitor tracking
            client_ip = f"192.168.{random.randint(1, 100)}.{random.randint(1, 254)}"

            session = ChatSession.objects.create(
                chatbot=chatbot,
                site=chatbot.site,
                org_id=org.id,
                status='ended',
                device_type=random.choice(['desktop', 'desktop', 'desktop', 'mobile', 'tablet']),  # Desktop bias
                referrer=random.choice([None, 'https://google.com', 'https://google.com', 'https://linkedin.com', 'https://twitter.com']),
                client_ip=client_ip,
                session_data={
                    'visitor_name': conv.get('visitor_name'),
                    'visitor_email': conv.get('visitor_email'),
                    'page_url': f"https://{chatbot.site.domain}/",
                },
            )
            # Update started_at AND created_at to the session_time (override auto_now_add)
            ChatSession.objects.filter(id=session.id).update(started_at=session_time, created_at=session_time)
            sessions_created += 1

            # Add messages
            message_time = session_time
            for j, (role, content) in enumerate(conv['messages']):
                message_time += timedelta(seconds=random.randint(5, 60))
                msg = ChatMessage.objects.create(
                    session=session,
                    role=role,
                    content=content,
                    conversation_turn=j // 2 + 1,
                    query_category=conv.get('category') if role == 'user' else None,
                    latency_ms=random.randint(300, 2500) if role == 'assistant' else 0,
                )

                # Update created_at to proper historical time (override auto_now_add)
                ChatMessage.objects.filter(id=msg.id).update(created_at=message_time)
                messages_created += 1

                # Add feedback to last assistant message if specified
                if role == 'assistant' and j == len(conv['messages']) - 1 and conv.get('feedback'):
                    # Map positive/negative to like/dislike for ChatMessage.feedback field
                    message_feedback = 'like' if conv['feedback'] == 'positive' else 'dislike'
                    msg.feedback = message_feedback
                    msg.save(update_fields=['feedback'])
                    
                    
                    ChatFeedback.objects.create(
                        message=msg,
                        feedback_type=conv['feedback'],
                    )
            
            # Update last_activity for the session to match the last message time
            ChatSession.objects.filter(id=session.id).update(last_activity=message_time)


        # Create additional random sessions for volume - spread across 60 days
        for idx in range(random.randint(20, 40)):
            # More recent days have more sessions (realistic growth pattern)
            if idx < 10:
                days_ago = random.randint(0, 7)   # Last week - most activity
            elif idx < 20:
                days_ago = random.randint(7, 21)  # 1-3 weeks ago
            else:
                days_ago = random.randint(21, 60) # Older sessions
            
            # Uniform hour distribution (0-23) for uniform weekly chart
            hours_offset = random.randint(0, 23)
            session_time = now - timedelta(days=days_ago, hours=hours_offset, minutes=random.randint(0, 59))
            
            # Generate random client IP for visitor tracking
            client_ip = f"192.168.{random.randint(1, 100)}.{random.randint(1, 254)}"

            session = ChatSession.objects.create(
                chatbot=chatbot,
                site=chatbot.site,
                org_id=org.id,
                status=random.choice(['ended', 'ended', 'ended', 'active'] if days_ago < 2 else ['ended']),
                device_type=random.choice(['desktop', 'desktop', 'mobile', 'tablet']),
                client_ip=client_ip,
            )
            # Update started_at AND created_at to the session_time
            ChatSession.objects.filter(id=session.id).update(started_at=session_time, created_at=session_time)
            sessions_created += 1

            # Add 2-6 messages
            message_time = session_time
            num_messages = random.randint(2, 6)
            last_assistant_msg = None
            for j in range(num_messages):
                role = 'user' if j % 2 == 0 else 'assistant'
                message_time += timedelta(seconds=random.randint(10, 120))
                msg = ChatMessage.objects.create(
                    session=session,
                    role=role,
                    content=f"Sample {role} message #{j+1}" if role == 'user' else "Thank you for your question. Let me help you with that.",
                    conversation_turn=j // 2 + 1,
                    latency_ms=random.randint(300, 2500) if role == 'assistant' else 0,
                )

                # Update created_at to proper historical time (override auto_now_add)
                ChatMessage.objects.filter(id=msg.id).update(created_at=message_time)
                if role == 'assistant':
                    last_assistant_msg = msg
                messages_created += 1

            # Add feedback to ~40% of sessions (mix of positive and negative)
            if last_assistant_msg and random.random() < 0.4:
                feedback_type = random.choices(
                    ['positive', 'negative'],
                    weights=[75, 25]  # 75% positive, 25% negative
                )[0]
                # Map positive/negative to like/dislike for ChatMessage.feedback field
                message_feedback = 'like' if feedback_type == 'positive' else 'dislike'
                
                # Update ChatMessage.feedback field (used by analytics queries)
                last_assistant_msg.feedback = message_feedback
                last_assistant_msg.save(update_fields=['feedback'])
                
                # Also create ChatFeedback record for detailed feedback
                ChatFeedback.objects.create(
                    message=last_assistant_msg,
                    feedback_type=feedback_type,
                )

            # Update last_activity for the session to match the last message time
            ChatSession.objects.filter(id=session.id).update(last_activity=message_time)


        return sessions_created, messages_created

    def _create_lead_scores(self, chatbots, org):
        """Create lead score entries with complete data for UI display"""
        now = timezone.now()
        leads_created = 0

        # Complete lead templates with all fields needed for the UI
        lead_templates = [
            {
                'visitor_name': 'John Smith',
                'visitor_email': 'john.smith@enterprise.com',
                'company_name': 'Enterprise Solutions Inc.',
                'job_title': 'VP of Engineering',
                'team_size': '200-500',
                'industry': 'Enterprise Software',
                'total_score': 92,
                'engagement_score': 45,
                'intent_score': 47,
                'priority': 'hot',
                'detected_intent': 'demo_request',
                'sentiment': 'positive',
                'urgency': 'high',
                'geo_location': 'San Francisco, CA',
                'device_type': 'desktop',
                'key_questions': [
                    'What are the enterprise plan features?',
                    'Can you tell me more about custom integrations?',
                    'How do I schedule a demo?'
                ],
                'conversation_summary': 'High-intent enterprise prospect interested in custom integrations and demo scheduling. Asked detailed questions about enterprise features and expressed interest in implementation timeline.',
                'buying_signals': ['Asked for demo', 'Inquired about enterprise pricing', 'Mentioned implementation timeline'],
                'objections': [],
                'competitor_mentions': ['Intercom', 'Drift'],
                'budget_signals': 'Q1 budget approved',
                'timeline': 'Next 30 days',
                'use_case': 'Customer support automation for enterprise SaaS',
                'follow_up_action': 'Schedule demo call within 24 hours',
                'talking_points': ['ROI calculator for enterprise', 'Custom integration capabilities', 'Dedicated account management'],
                'content_gaps': [],
                'reasoning': 'Enterprise VP with clear timeline and budget. Multiple high-intent signals including demo request and pricing inquiry.',
            },
            {
                'visitor_name': 'Sarah Johnson',
                'visitor_email': 'sarah@startup.io',
                'company_name': 'Startup Innovation',
                'job_title': 'Founder & CEO',
                'team_size': '10-50',
                'industry': 'Technology Startup',
                'total_score': 78,
                'engagement_score': 38,
                'intent_score': 40,
                'priority': 'warm',
                'detected_intent': 'pricing_inquiry',
                'sentiment': 'positive',
                'urgency': 'medium',
                'geo_location': 'Austin, TX',
                'device_type': 'desktop',
                'key_questions': [
                    'How do I get started with my first chatbot?',
                    'What are the pricing plans?',
                    'How long does indexing take?'
                ],
                'conversation_summary': 'Startup founder exploring chatbot solutions for customer support. Showed strong interest in getting started quickly and understanding pricing options.',
                'buying_signals': ['Asked about pricing', 'Ready to start immediately'],
                'objections': ['Budget constraints mentioned'],
                'competitor_mentions': [],
                'budget_signals': 'Looking for startup-friendly pricing',
                'timeline': 'This week',
                'use_case': 'First chatbot for startup website',
                'follow_up_action': 'Send startup discount offer',
                'talking_points': ['Startup-friendly pricing', 'Quick setup process', 'Scalability as they grow'],
                'content_gaps': ['Startup case studies'],
                'reasoning': 'Early-stage startup with immediate need. Price-sensitive but high urgency to implement.',
            },
            {
                'visitor_name': 'Mike Chen',
                'visitor_email': 'mike@techfirm.com',
                'company_name': 'TechFirm LLC',
                'job_title': 'Technical Lead',
                'team_size': '50-100',
                'industry': 'IT Consulting',
                'total_score': 65,
                'engagement_score': 32,
                'intent_score': 33,
                'priority': 'warm',
                'detected_intent': 'support',
                'sentiment': 'neutral',
                'urgency': 'medium',
                'geo_location': 'Seattle, WA',
                'device_type': 'desktop',
                'key_questions': [
                    'The chatbot is giving wrong answers about our pricing',
                    'How do I update the knowledge base?',
                    'How long until the changes take effect?'
                ],
                'conversation_summary': 'Existing customer experiencing issues with chatbot answers. Needed help with re-indexing and knowledge base updates.',
                'buying_signals': ['Active user seeking support'],
                'objections': ['Concerned about answer accuracy'],
                'competitor_mentions': [],
                'budget_signals': None,
                'timeline': None,
                'use_case': 'Updating existing chatbot knowledge base',
                'follow_up_action': 'Follow up on re-indexing success',
                'talking_points': ['Knowledge base best practices', 'Scheduled re-indexing options'],
                'content_gaps': ['Knowledge base troubleshooting guide'],
                'reasoning': 'Existing customer with support needs. Good opportunity to improve experience and prevent churn.',
            },
            {
                'visitor_name': 'Emily Davis',
                'visitor_email': 'emily@agency.co',
                'company_name': 'Creative Agency Partners',
                'job_title': 'Agency Director',
                'team_size': '20-50',
                'industry': 'Digital Marketing Agency',
                'total_score': 88,
                'engagement_score': 44,
                'intent_score': 44,
                'priority': 'hot',
                'detected_intent': 'partnership',
                'sentiment': 'positive',
                'urgency': 'high',
                'geo_location': 'New York, NY',
                'device_type': 'mobile',
                'key_questions': [
                    'Can I white-label the chatbot for my clients?',
                    'We manage 20+ client websites. Is there a bulk discount?',
                    'Can you arrange a call with partnerships team?'
                ],
                'conversation_summary': 'Agency director interested in white-label solution for multiple clients. High volume potential with 20+ websites. Requested partnership discussion.',
                'buying_signals': ['Asked about white-label', 'Mentioned volume (20+ clients)', 'Requested partnership call'],
                'objections': [],
                'competitor_mentions': ['Chatfuel'],
                'budget_signals': 'Volume discount inquiry',
                'timeline': 'Starting next quarter',
                'use_case': 'White-label chatbots for agency clients',
                'follow_up_action': 'Connect with partnerships team immediately',
                'talking_points': ['Agency partner program benefits', 'Volume discounts', 'White-label customization'],
                'content_gaps': [],
                'reasoning': 'High-value agency partnership opportunity. 20+ potential deployments with white-label needs.',
            },
            {
                'visitor_name': 'David Wilson',
                'visitor_email': 'david@bigcorp.com',
                'company_name': 'BigCorp International',
                'job_title': 'Chief Technology Officer',
                'team_size': '1000+',
                'industry': 'Financial Services',
                'total_score': 95,
                'engagement_score': 48,
                'intent_score': 47,
                'priority': 'hot',
                'detected_intent': 'enterprise_inquiry',
                'sentiment': 'positive',
                'urgency': 'high',
                'geo_location': 'Chicago, IL',
                'device_type': 'desktop',
                'key_questions': [
                    'What security certifications do you have?',
                    'Can we deploy on-premise?',
                    'What is your enterprise SLA?'
                ],
                'conversation_summary': 'Enterprise CTO evaluating chatbot solutions for large financial services company. Strong focus on security, compliance, and enterprise SLA requirements.',
                'buying_signals': ['CTO-level engagement', 'Asked about enterprise SLA', 'Security compliance focus'],
                'objections': ['Needs SOC 2 compliance confirmation'],
                'competitor_mentions': ['IBM Watson', 'Salesforce Einstein'],
                'budget_signals': 'Enterprise budget available',
                'timeline': 'Q2 implementation',
                'use_case': 'Enterprise-wide customer service automation',
                'follow_up_action': 'Send security whitepaper and schedule executive briefing',
                'talking_points': ['SOC 2 compliance', 'Enterprise SLA details', 'On-premise deployment options'],
                'content_gaps': ['Security compliance documentation'],
                'reasoning': 'Enterprise CTO with clear budget and timeline. High-value opportunity requiring executive-level engagement.',
            },
            {
                'visitor_name': 'Anonymous Visitor',
                'visitor_email': None,
                'company_name': None,
                'job_title': None,
                'team_size': None,
                'industry': None,
                'total_score': 35,
                'engagement_score': 18,
                'intent_score': 17,
                'priority': 'cold',
                'detected_intent': 'information',
                'sentiment': 'neutral',
                'urgency': 'low',
                'geo_location': 'London, UK',
                'device_type': 'mobile',
                'key_questions': [
                    'What programming languages do you support?',
                    'Do you have webhooks?'
                ],
                'conversation_summary': 'Anonymous visitor asking technical questions about API capabilities. Early research phase with no buying signals.',
                'buying_signals': [],
                'objections': [],
                'competitor_mentions': [],
                'budget_signals': None,
                'timeline': None,
                'use_case': 'API research',
                'follow_up_action': 'No immediate action needed',
                'talking_points': ['API documentation', 'Developer resources'],
                'content_gaps': [],
                'reasoning': 'Early-stage research with minimal engagement. No contact information provided.',
            },
        ]

        used_session_ids = set()

        for chatbot in chatbots:
            # Get available sessions for this chatbot
            available_sessions = list(ChatSession.objects.filter(chatbot=chatbot).exclude(id__in=used_session_ids))

            for i, template in enumerate(random.sample(lead_templates, min(4, len(lead_templates)))):
                if i >= len(available_sessions):
                    # No more available sessions for this chatbot
                    break

                session = available_sessions[i]
                used_session_ids.add(session.id)

                days_ago = random.randint(0, 14)
                session_date = (now - timedelta(days=days_ago)).date()

                # Build complete llm_insights structure
                llm_insights = {
                    'analyzed_by_llm': True,
                    'model_used': 'gpt-4o-mini',
                    'intent': {
                        'primary': template['detected_intent'],
                        'confidence': random.randint(75, 95) if template['priority'] == 'hot' else random.randint(55, 75),
                        'buying_signals': template.get('buying_signals', []),
                        'objections': template.get('objections', []),
                    },
                    'entities': {
                        'company_name': template.get('company_name'),
                        'contact_email': template.get('visitor_email'),
                        'contact_name': template.get('visitor_name'),
                        'job_title': template.get('job_title'),
                        'team_size': template.get('team_size'),
                        'industry': template.get('industry'),
                        'budget_signals': template.get('budget_signals'),
                        'timeline': template.get('timeline'),
                        'use_case': template.get('use_case'),
                    },
                    'sentiment': template.get('sentiment', 'neutral'),
                    'urgency': template.get('urgency', 'medium'),
                    'engagement_quality': 'high' if template['total_score'] >= 80 else 'medium' if template['total_score'] >= 50 else 'low',
                    'competitor_mentions': template.get('competitor_mentions', []),
                    'recommendations': {
                        'follow_up_action': template.get('follow_up_action', ''),
                        'talking_points': template.get('talking_points', []),
                        'content_gaps': template.get('content_gaps', []),
                    },
                    'reasoning': template.get('reasoning', ''),
                }

                # Determine feedback based on sentiment
                had_positive = template.get('sentiment') == 'positive' and random.random() > 0.3
                had_negative = template.get('sentiment') == 'negative' or (template.get('detected_intent') == 'support' and random.random() > 0.7)

                LeadScore.objects.create(
                    org_id=org.id,
                    chatbot=chatbot,
                    session=session,
                    session_date=session_date,
                    total_score=template['total_score'],
                    engagement_score=template['engagement_score'],
                    intent_score=template['intent_score'],
                    priority=template['priority'],
                    detected_intent=template['detected_intent'],
                    message_count=random.randint(4, 12),
                    session_duration_seconds=random.randint(120, 900),
                    source_url=f"https://{chatbot.site.domain}/",
                    geo_location=template.get('geo_location'),
                    device_type=template.get('device_type', 'desktop'),
                    key_questions=template.get('key_questions', []),
                    conversation_summary=template.get('conversation_summary', ''),
                    had_positive_feedback=had_positive,
                    had_negative_feedback=had_negative,
                    llm_insights=llm_insights,
                )
                leads_created += 1

        return leads_created

    def _create_weekly_reports(self, user, org, chatbots):
        """Create weekly reports for the last 4 weeks"""
        now = timezone.now()

        for weeks_ago in range(4):
            week_start = (now - timedelta(weeks=weeks_ago)).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=(now - timedelta(weeks=weeks_ago)).weekday())

            for chatbot in chatbots:
                total_leads = random.randint(5, 25)
                hot_leads = random.randint(1, 5)
                high_leads = random.randint(2, 8)

                WeeklyLeadsReport.objects.create(
                    user=user,
                    org=org,
                    chatbot=chatbot,
                    week_start=week_start,
                    week_end=week_start + timedelta(days=6),
                    total_leads=total_leads,
                    hot_leads=hot_leads,
                    warm_leads=high_leads,
                    cold_leads=max(0, total_leads - hot_leads - high_leads),
                    total_sessions=random.randint(50, 150),
                    email_sent=weeks_ago > 0,
                    email_sent_at=week_start + timedelta(days=7, hours=9) if weeks_ago > 0 else None,
                    report_data={
                        'average_score': round(random.uniform(55.0, 80.0), 1),
                        'intent_breakdown': {
                            'pricing_inquiry': random.randint(5, 15),
                            'demo_request': random.randint(3, 10),
                            'feature_inquiry': random.randint(2, 8),
                        },
                        'top_questions': [
                            'What are your pricing plans?',
                            'Can I get a demo?',
                            'How do I integrate with my website?',
                        ],
                    },
                )

    def _create_usage_events(self, org, sites, chatbots):
        """Create usage events for analytics charts"""
        now = timezone.now()

        # Create events spread over the last 60 days with growth pattern
        for days_ago in range(60):
            event_date = now - timedelta(days=days_ago)
            
            # Growth pattern: more recent days have more activity
            if days_ago < 7:
                activity_multiplier = 1.0  # Full activity this week
            elif days_ago < 14:
                activity_multiplier = 0.85  # 85% last week
            elif days_ago < 30:
                activity_multiplier = 0.7   # 70% 2-4 weeks ago
            else:
                activity_multiplier = 0.5   # 50% older (simulating growth)

            # Chat events (more on weekdays)
            base_chat = 60 if event_date.weekday() < 5 else 20
            chat_count = int(random.randint(int(base_chat * 0.5), base_chat) * activity_multiplier)
            for _ in range(chat_count):
                chatbot = random.choice(chatbots)
                UsageEvent.objects.create(
                    org_id=org.id,
                    site_id=chatbot.site.id,
                    chatbot_id=chatbot.id,
                    type='chat',
                    units=1,
                    occurred_at=event_date.replace(
                        hour=random.randint(8, 22),
                        minute=random.randint(0, 59)
                    ),
                )

            # Query events
            base_query = 120 if event_date.weekday() < 5 else 50
            query_count = int(random.randint(int(base_query * 0.5), base_query) * activity_multiplier)
            for _ in range(query_count):
                site = random.choice(sites)
                UsageEvent.objects.create(
                    org_id=org.id,
                    site_id=site.id,
                    type='query',
                    units=1,
                    occurred_at=event_date.replace(
                        hour=random.randint(0, 23),
                        minute=random.randint(0, 59)
                    ),
                )

