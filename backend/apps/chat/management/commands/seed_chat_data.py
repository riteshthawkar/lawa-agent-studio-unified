import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.chatbot.models import Chatbot
from apps.chat.models import ChatSession, ChatMessage
from apps.sites.models import Site

class Command(BaseCommand):
    help = 'Seeds database with sample chat data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding chat data...')

        # Get the first available site or create one if none exists
        site = Site.objects.first()
        if not site:
            self.stdout.write(self.style.WARNING('No site found. Creating a test site...'))
            site = Site.objects.create(domain='example.com', name='Example Site')

        # Get the first chatbot or create one if none exists
        chatbot = Chatbot.objects.first()
        if not chatbot:
            self.stdout.write(self.style.WARNING('No chatbot found. Creating a test chatbot...'))
            chatbot = Chatbot.objects.create(
                site_id=site.id,
                name='Test Assistant',
                status='active'
            )
        
        # Ensure chatbot has site_id
        if not chatbot.site_id:
             chatbot.site_id = site.id
             chatbot.save()

        # Sample data sources - full geo data
        geo_locations = [
            {'code': 'US', 'name': 'United States', 'region': 'California', 'city': 'San Francisco'},
            {'code': 'US', 'name': 'United States', 'region': 'New York', 'city': 'New York City'},
            {'code': 'US', 'name': 'United States', 'region': 'Texas', 'city': 'Austin'},
            {'code': 'GB', 'name': 'United Kingdom', 'region': 'England', 'city': 'London'},
            {'code': 'GB', 'name': 'United Kingdom', 'region': 'Scotland', 'city': 'Edinburgh'},
            {'code': 'CA', 'name': 'Canada', 'region': 'Ontario', 'city': 'Toronto'},
            {'code': 'CA', 'name': 'Canada', 'region': 'British Columbia', 'city': 'Vancouver'},
            {'code': 'AU', 'name': 'Australia', 'region': 'New South Wales', 'city': 'Sydney'},
            {'code': 'DE', 'name': 'Germany', 'region': 'Bavaria', 'city': 'Munich'},
            {'code': 'DE', 'name': 'Germany', 'region': 'Berlin', 'city': 'Berlin'},
            {'code': 'FR', 'name': 'France', 'region': 'Île-de-France', 'city': 'Paris'},
            {'code': 'IN', 'name': 'India', 'region': 'Maharashtra', 'city': 'Mumbai'},
            {'code': 'IN', 'name': 'India', 'region': 'Karnataka', 'city': 'Bangalore'},
            {'code': 'JP', 'name': 'Japan', 'region': 'Tokyo', 'city': 'Tokyo'},
            {'code': 'SG', 'name': 'Singapore', 'region': 'Singapore', 'city': 'Singapore'},
            {'code': 'AE', 'name': 'UAE', 'region': 'Dubai', 'city': 'Dubai'},
            {'code': 'BR', 'name': 'Brazil', 'region': 'São Paulo', 'city': 'São Paulo'},
            {'code': 'NL', 'name': 'Netherlands', 'region': 'North Holland', 'city': 'Amsterdam'},
        ]
        feedbacks = ['like', 'dislike', 'no_feedback', 'no_feedback', 'no_feedback']
        
        user_messages = [
            "How do I reset my password?",
            "What are your pricing plans?",
            "Can I cancel my subscription anytime?",
            "Do you offer student discounts?",
            "I'm having trouble logging in.",
            "Where can I find the API documentation?",
            "Is there a free trial?",
            "How do I contact support?",
            "My payment failed, what should I do?",
            "Can I change my email address?",
             "What is the difference between Pro and Enterprise?",
             "How do I export my data?",
             "Do you have an iOS app?",
             "Is my data secure?",
             "How do I invite team members?"
        ]

        assistant_responses = [
            "You can reset your password by clicking on the 'Forgot Password' link on the login page.",
            "We offer three pricing plans: Basic, Pro, and Enterprise. You can view the details on our pricing page.",
            "Yes, you can cancel your subscription at any time from your account settings.",
            "We do offer a 20% discount for students with a valid .edu email address.",
            "I'm sorry to hear that. Please try clearing your browser cache or resetting your password.",
            "Our API documentation is available at docs.example.com.",
            "Yes, we offer a 14-day free trial for all new users.",
            "You can contact support by emailing support@example.com or using the live chat widget.",
            "Please check your card details and try again. If the issue persists, contact your bank.",
            "Yes, you can update your email address in the 'Profile' section of your account settings.",
            "Pro is for individuals, while Enterprise offers advanced features for teams.",
            "You can export your data as a CSV file from the settings page.",
            "Yes, our iOS app is available on the App Store.",
            "We use bank-level encryption to ensure your data is safe.",
            "You can invite team members from the 'Team' tab in your dashboard."
        ]

        # Generate sessions for the last 30 days
        sessions_created = 0
        now = timezone.now()

        for i in range(50):  # Create 50 sessions
            # Random time in last 30 days
            days_ago = random.randint(0, 30)
            hours_ago = random.randint(0, 23)
            minutes_ago = random.randint(0, 59)
            started_at = now - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
            
            # Simple duration simulation
            duration_minutes = random.randint(1, 20)
            ended_at = started_at + timedelta(minutes=duration_minutes)
            
            # Select a random geo location
            geo = random.choice(geo_locations)

            session = ChatSession.objects.create(
                site=site,
                chatbot=chatbot,
                started_at=started_at,
                last_activity=ended_at, # Approximate
                ended_at=ended_at,
                status='ended',
                geo_country_code=geo['code'],
                geo_country_name=geo['name'],
                geo_region=geo['region'],
                geo_city=geo['city'],
                session_data={"platform": "web", "browser": "Chrome"}
            )

            # Create random number of messages (2-10)
            num_messages = random.randint(1, 5) * 2 # Ensure even pairs mostly
            
            for j in range(num_messages):
                msg_time = started_at + timedelta(minutes=j*2)
                
                # User message
                user_msg_content = random.choice(user_messages)
                user_msg = ChatMessage.objects.create(
                    session=session,
                    role='user',
                    content=user_msg_content,
                    created_at=msg_time,
                    tokens_in=len(user_msg_content.split()),
                    latency_ms=0
                )
                ChatMessage.objects.filter(id=user_msg.id).update(created_at=msg_time)

                # Assistant message
                # Find a somewhat relevant response based on index if possible, else random
                try:
                    msg_index = user_messages.index(user_msg_content)
                    assistant_msg_content = assistant_responses[msg_index]
                except ValueError:
                    assistant_msg_content = random.choice(assistant_responses)

                feedback = random.choice(feedbacks)
                
                # Only set feedback on assistant messages sometimes
                msg_feedback = feedback if random.random() > 0.7 else 'no_feedback'
                
                asst_msg_time = msg_time + timedelta(seconds=random.randint(1, 10))
                asst_msg = ChatMessage.objects.create(
                    session=session,
                    role='assistant',
                    content=assistant_msg_content,
                    created_at=asst_msg_time,
                    tokens_out=len(assistant_msg_content.split()),
                    latency_ms=random.randint(500, 2000),
                    feedback=msg_feedback
                )
                ChatMessage.objects.filter(id=asst_msg.id).update(created_at=asst_msg_time)

            # Force update session timestamps
            ChatSession.objects.filter(id=session.id).update(
                created_at=started_at,
                started_at=started_at,
                last_activity=ended_at
            )
            
            sessions_created += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully created {sessions_created} chat sessions with messages'))
