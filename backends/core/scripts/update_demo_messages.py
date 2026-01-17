"""
Script to update chat messages with realistic demo content.
Run with: python3 scripts/update_demo_messages.py
"""
import os
import sys
import django
import random

# Setup Django
sys.path.insert(0, '/Users/ritesh.thawkar/Ritesh/lawa-webbotify-project/backends/core')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
django.setup()

from apps.chat.models import ChatSession, ChatMessage

# Realistic demo conversations - pairs of (user_query, assistant_response)
DEMO_CONVERSATIONS = [
    # Pricing questions
    ("What are your pricing plans?", "We offer three tiers:\n\n• **Basic (Free)**: 1 chatbot, 100 messages/month, basic analytics\n• **Premium ($29/mo)**: Unlimited chatbots, 10K messages/month, advanced analytics, lead capture\n• **Enterprise (Custom)**: Unlimited everything, dedicated support, SSO, custom integrations\n\nAll paid plans include a 14-day free trial!"),
    
    ("How much does the premium plan cost?", "The Premium plan is **$29/month** (or $24/month if billed annually). It includes unlimited chatbots, up to 10,000 messages per month, advanced analytics, lead scoring, and priority support. You can start with a free 14-day trial!"),
    
    ("Do you offer a free trial?", "Yes! We offer a **14-day free trial** of our Premium plan with no credit card required. You'll get access to all Premium features including advanced analytics, lead capture, and unlimited chatbots."),
    
    # Feature questions
    ("Can I customize the chatbot appearance?", "Absolutely! You can fully customize your chatbot's appearance:\n\n• **Colors**: Primary color, background, text colors\n• **Position**: Bottom-right, bottom-left, or embedded\n• **Branding**: Add your logo, customize the chat header\n• **Messages**: Set welcome message, placeholder text, conversation starters\n• **Behavior**: Auto-open, show/hide on specific pages\n\nAll customizations are available in your chatbot dashboard."),
    
    ("What languages do you support?", "Our AI chatbots support **50+ languages** including:\n\n🇺🇸 English, 🇪🇸 Spanish, 🇫🇷 French, 🇩🇪 German, 🇮🇳 Hindi, 🇸🇦 Arabic, 🇨🇳 Chinese, 🇯🇵 Japanese, 🇰🇷 Korean, 🇵🇹 Portuguese, and many more.\n\nThe AI automatically detects the user's language and responds accordingly!"),
    
    ("How do I embed the chatbot on my website?", "It's super easy! Just 2 steps:\n\n1. Copy the embed code from your chatbot dashboard\n2. Paste it before the `</body>` tag on your website\n\nWe also provide ready-made plugins for:\n• WordPress\n• Shopify\n• Webflow\n• Wix\n• Squarespace\n\nNeed help? Check our integration guides or reach out to support!"),
    
    ("Can I train the chatbot on my own content?", "Yes! There are several ways to train your chatbot:\n\n📄 **Documents**: Upload PDFs, Word docs, text files\n🌐 **Website**: We crawl and index your entire website automatically\n📝 **FAQ**: Add custom Q&A pairs\n🔗 **URLs**: Add specific pages to index\n\nThe AI learns from your content and provides accurate, context-aware responses to your visitors."),
    
    # Technical questions  
    ("What is the response time of the chatbot?", "Our chatbots are blazing fast! ⚡\n\n• **Average response time**: Under 2 seconds\n• **99.9% uptime** SLA for Enterprise customers\n• We use advanced LLMs optimized for speed and accuracy\n• Responses are streamed in real-time for the best user experience"),
    
    ("Is there an API available?", "Yes! We provide a comprehensive **REST API** for all plans:\n\n• Send messages programmatically\n• Access conversation history\n• Retrieve analytics data\n• Manage chatbots and settings\n• Webhook integrations for real-time events\n\nFull API documentation is available in your dashboard under Developers > API."),
    
    ("How secure is my data?", "Security is our top priority! 🔒\n\n• **Encryption**: AES-256 at rest, TLS 1.3 in transit\n• **Compliance**: SOC 2 Type II, GDPR, CCPA ready\n• **Data isolation**: Your data is never used to train our models\n• **Access control**: Role-based permissions, SSO (Enterprise)\n• **Hosting**: AWS with multi-region redundancy\n\nEnterprise customers can request a security audit report."),
    
    # Support questions
    ("How do I contact support?", "We're here to help! 📞\n\n• **Help Center**: Comprehensive docs and guides\n• **Live Chat**: Available in your dashboard\n• **Email**: support@lawaai.com\n• **Priority Support**: Premium & Enterprise customers\n• **Dedicated CSM**: Enterprise customers\n\nOur average response time is under 2 hours during business hours."),
    
    ("I'm having trouble with the integration", "I'm sorry to hear that! Let me help troubleshoot:\n\n**Common issues**:\n1. Make sure the script is placed before `</body>`\n2. Check if there are any Content Security Policy (CSP) blocks\n3. Clear your browser cache\n4. Verify the chatbot is published (switch on in dashboard)\n\nCan you share:\n• Your website URL?\n• Any console errors you see?\n\nOur support team is also available 24/7 to help!"),
    
    ("Can you help me set up my first chatbot?", "Of course! Here's a quick guide to get started:\n\n**Step 1**: Add your website URL in Projects\n**Step 2**: Wait for indexing to complete (usually 2-5 min)\n**Step 3**: Customize appearance in Chatbot Settings\n**Step 4**: Copy embed code and add to your website\n**Step 5**: Test it out!\n\n📹 We also have video tutorials in our Help Center.\n\nNeed a walkthrough? Our onboarding team offers free setup calls for Premium users!"),
    
    # Use case questions
    ("Is this good for e-commerce?", "Absolutely! E-commerce is one of our most popular use cases! 🛍️\n\n**Benefits**:\n• 24/7 product recommendations\n• Instant answers to shipping, returns, sizing questions\n• Order tracking assistance\n• Reduce cart abandonment by 25%\n• Increase conversions by up to 30%\n\nMany Shopify stores use our chatbots to boost sales while reducing support tickets."),
    
    ("Can I use this for customer support?", "Yes! We're perfect for customer support! 💬\n\n**Results our customers see**:\n• **40-60% reduction** in support tickets\n• **24/7 availability** without hiring night staff\n• **Instant responses** to common questions\n• **Seamless handoff** to human agents when needed\n\nIntegrates with Zendesk, Intercom, Freshdesk, and more."),
    
    ("Does it work for SaaS products?", "Definitely! SaaS companies love us! 🚀\n\n**Use cases**:\n• **User onboarding**: Guide new users through features\n• **Documentation search**: Instant answers from your docs\n• **Feature explanations**: Help users discover functionality\n• **Billing questions**: Answer pricing/upgrade queries\n• **Bug reporting**: Collect structured feedback\n\nWorks great alongside your existing support tools!"),
    
    # Account questions
    ("How do I upgrade my plan?", "Upgrading is easy! 🎉\n\n1. Go to **Settings > Billing** in your dashboard\n2. Click **Upgrade Plan**\n3. Choose Premium or Enterprise\n4. Enter payment details\n\nChanges take effect immediately. You'll be prorated for any remaining time on your current plan.\n\nNeed Enterprise? Contact our sales team for custom pricing!"),
    
    ("Can I cancel anytime?", "Yes, absolutely! No lock-in contracts. 🙌\n\n• Cancel anytime from Settings > Billing\n• Your access continues until the end of your billing period\n• We'll save your data for 30 days in case you want to return\n• No cancellation fees\n\nWe'd love feedback on why you're leaving so we can improve!"),
    
    ("How do I add team members?", "Adding team members is simple:\n\n1. Go to **Settings > Team**\n2. Click **Invite Member**\n3. Enter their email\n4. Choose their role:\n   • **Admin**: Full access\n   • **Editor**: Can manage chatbots, view analytics\n   • **Viewer**: Read-only access\n\nPremium includes 3 team seats, Enterprise is unlimited."),
    
    # Analytics questions
    ("What analytics do you provide?", "We offer comprehensive analytics! 📊\n\n**Conversation Analytics**:\n• Total conversations & messages\n• User satisfaction (thumbs up/down)\n• Top questions asked\n• Unanswered questions\n\n**Lead Analytics** (Premium+):\n• Lead scoring & priority\n• Conversion tracking\n• Geographic distribution\n\n**Custom Reports** (Enterprise):\n• Scheduled email reports\n• Data export to your BI tools"),
    
    ("Can I export my data?", "Yes! Data export is available:\n\n**What you can export**:\n• Conversation transcripts (CSV/JSON)\n• Analytics data\n• Lead information\n• Usage metrics\n\n**Export options**:\n• Manual download from dashboard\n• API access for automation\n• Webhook events (Enterprise)\n• Data warehouse sync (Enterprise)\n\nYour data is always yours!"),
    
    ("How do I track conversions?", "Conversion tracking is built-in! 🎯\n\n1. Go to **Analytics > Goals**\n2. Create a new goal:\n   • Form submissions\n   • Button clicks\n   • Custom events\n   • URL visits after chat\n3. View conversion rates in your dashboard\n\nPremium users get advanced attribution tracking to see which conversations led to conversions."),
]

def update_demo_messages():
    # Target the org that has demo data
    org_id = '7f03ab9e-ef89-4351-aa5b-3b725ebfd313'
    
    sessions = ChatSession.objects.filter(org_id=org_id).order_by('-created_at')
    print(f"Found {sessions.count()} chat sessions for org {org_id}")

    if sessions.count() == 0:
        print("No sessions found, nothing to update")
        return

    updated_count = 0
    session_count = 0

    for session in sessions:
        messages = list(ChatMessage.objects.filter(session=session).order_by('created_at'))
        
        if len(messages) == 0:
            continue

        # Pick a random conversation
        user_query, assistant_response = random.choice(DEMO_CONVERSATIONS)
        session_count += 1

        # Update messages in pairs
        for i, message in enumerate(messages):
            if message.role == 'user':
                message.content = user_query
                message.save()
                updated_count += 1
                
            elif message.role == 'assistant':
                message.content = assistant_response
                message.save()
                updated_count += 1

    print(f"✅ Updated {updated_count} messages across {session_count} sessions")

if __name__ == '__main__':
    update_demo_messages()
