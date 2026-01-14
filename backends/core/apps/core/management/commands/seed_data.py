import uuid
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization, Membership
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from apps.indexing.models import IndexingJob
from apps.usage.models import Quota
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed database with sample data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database...')
        
        # Create sample user
        user, created = User.objects.get_or_create(
            email='admin@example.com',
            defaults={
                'username': 'admin',
                'name': 'Admin User',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            user.set_password('admin123')
            user.save()
            self.stdout.write(f'Created user: {user.email}')
        
        # Create sample organization
        org, created = Organization.objects.get_or_create(
            slug='demo-org',
            defaults={
                'name': 'Demo Organization',
                'status': 'active',
                'plan_tier': 'trial'
            }
        )
        if created:
            self.stdout.write(f'Created organization: {org.name}')
        
        # Create membership
        membership, created = Membership.objects.get_or_create(
            user=user,
            organization=org,
            defaults={'role': 'owner'}
        )
        if created:
            self.stdout.write(f'Created membership: {user.email} -> {org.name}')
        
        # Create sample sites
        site1, created = Site.objects.get_or_create(
            org_id=org.id,
            domain='https://example.com',
            defaults={
                'verification_method': 'dns',
                'status': 'pending'
            }
        )
        if created:
            self.stdout.write(f'Created site: {site1.domain}')
        
        site2, created = Site.objects.get_or_create(
            org_id=org.id,
            domain='https://demo-site.com',
            defaults={
                'verification_method': 'file',
                'status': 'active',
                'verified_at': timezone.now()
            }
        )
        if created:
            self.stdout.write(f'Created verified site: {site2.domain}')
        
        # Create sample chatbot
        chatbot, created = Chatbot.objects.get_or_create(
            org_id=org.id,
            site_id=site2.id,
            name='Demo Chatbot',
            defaults={
                'status': 'active',
                'model_provider': 'openai',
                'model_name': 'gpt-3.5-turbo',
                'retrieval_config': {
                    'top_k': 5,
                    'alpha': 0.7,
                    'filters': {},
                    'hybrid': True
                },
                'prompt_template': 'You are a helpful assistant for {site_name}. Answer questions based on the provided context.',
                'safety_config': {
                    'max_tokens': 1000,
                    'temperature': 0.7
                }
            }
        )
        if created:
            self.stdout.write(f'Created chatbot: {chatbot.name}')
        
        # Create chatbot style
        style, created = ChatbotStyle.objects.get_or_create(
            chatbot=chatbot,
            defaults={
                'theme': {
                    'primary_color': '#007bff',
                    'secondary_color': '#6c757d',
                    'font_family': 'Inter, sans-serif'
                },
                'widget_behavior': {
                    'position': 'bottom-right',
                    'auto_open': False,
                    'show_typing_indicator': True
                }
            }
        )
        if created:
            self.stdout.write(f'Created chatbot style for: {chatbot.name}')
        
        # Create sample chat session
        session, created = ChatSession.objects.get_or_create(
            org_id=org.id,
            chatbot_id=chatbot.id,
            site_id=site2.id,
            session_key='demo-session-001',
            defaults={
                'user_id': user.id,
                'meta': {'source': 'demo'}
            }
        )
        if created:
            self.stdout.write(f'Created chat session: {session.session_key}')
        
        # Create sample messages
        if not ChatMessage.objects.filter(session=session).exists():
            ChatMessage.objects.create(
                session=session,
                role='user',
                content='Hello, can you help me understand your services?',
                tokens_in=10,
                tokens_out=0
            )
            
            ChatMessage.objects.create(
                session=session,
                role='assistant',
                content='Hello! I\'d be happy to help you understand our services. Based on the information available, we offer comprehensive solutions for your business needs. How can I assist you further?',
                tokens_in=0,
                tokens_out=25,
                citations=[
                    {'url': 'https://demo-site.com/services', 'chunk_index': 1, 'score': 0.95}
                ],
                latency_ms=1200
            )
            self.stdout.write('Created sample chat messages')
        
        # Create sample indexing job
        job, created = IndexingJob.objects.get_or_create(
            org_id=org.id,
            site_id=site2.id,
            external_job_id='demo-job-001',
            defaults={
                'status': 'completed',
                'requested_by_user_id': user.id,
                'requested_params': {
                    'max_pages': 100,
                    'embed_model': 'text-embedding-ada-002'
                },
                'phase1_result': {
                    'pages_crawled': 95,
                    'pages_processed': 90
                },
                'phase2_result': {
                    'vectors_created': 1250,
                    'index_updated': True
                },
                'started_at': timezone.now() - timezone.timedelta(hours=2),
                'completed_at': timezone.now() - timezone.timedelta(hours=1)
            }
        )
        if created:
            self.stdout.write(f'Created indexing job: {job.external_job_id}')
        
        # Create sample quota
        quota, created = Quota.objects.get_or_create(
            org_id=org.id,
            period_start=timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            defaults={
                'period_end': timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timezone.timedelta(days=30),
                'limits': {
                    'max_pages': 1000,
                    'max_vectors': 10000,
                    'monthly_cost_cap': 10000,
                    'concurrent_jobs': 3
                },
                'usage': {
                    'pages': 95,
                    'vectors': 1250,
                    'cost_cents': 250,
                    'active_jobs': 0
                }
            }
        )
        if created:
            self.stdout.write(f'Created quota for organization: {org.name}')
        
        self.stdout.write(
            self.style.SUCCESS('Database seeded successfully!')
        )
        self.stdout.write('Sample data created:')
        self.stdout.write(f'- User: {user.email} (password: admin123)')
        self.stdout.write(f'- Organization: {org.name}')
        self.stdout.write(f'- Sites: {site1.domain} (pending), {site2.domain} (verified)')
        self.stdout.write(f'- Chatbot: {chatbot.name}')
        self.stdout.write(f'- Chat session with messages')
        self.stdout.write(f'- Indexing job: {job.external_job_id}')
        self.stdout.write(f'- Quota with usage tracking')
