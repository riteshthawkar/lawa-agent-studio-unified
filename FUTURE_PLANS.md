# Lawa Agent Studio - Future Plans & Roadmap

This document outlines planned features for Lawa Agent Studio, organized by priority and impact on growth.

---

## Table of Contents

1. [High-Impact Growth Features](#high-impact-growth-features)
2. [Retention & Stickiness Features](#retention--stickiness-features)
3. [Competitive Moat Features](#competitive-moat-features)
4. [Quick Wins](#quick-wins)
5. [Implementation Timeline](#implementation-timeline)

---

## High-Impact Growth Features

### 1. White-Label / Reseller Program

**Priority:** HIGH
**Estimated Effort:** 4-6 weeks
**Revenue Impact:** High (B2B channel)

#### Description
Allow agencies and partners to resell Lawa Agent Studio under their own brand, creating a distribution network without direct marketing spend.

#### Implementation Details

**Backend Changes:**
```
apps/
├── reseller/
│   ├── models.py
│   │   ├── ResellerAccount (partner details, commission rates)
│   │   ├── ResellerClient (clients under each reseller)
│   │   ├── ResellerInvoice (commission tracking)
│   │   └── WhiteLabelConfig (branding settings)
│   ├── views.py
│   │   ├── ResellerDashboardAPI
│   │   ├── ClientManagementAPI
│   │   └── CommissionReportsAPI
│   └── serializers.py
```

**Database Schema:**
```sql
-- Reseller account
CREATE TABLE reseller_accounts (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    company_name VARCHAR(255),
    commission_rate DECIMAL(5,2) DEFAULT 20.00,
    status ENUM('pending', 'approved', 'suspended'),
    custom_domain VARCHAR(255),
    created_at TIMESTAMP
);

-- White-label configuration
CREATE TABLE whitelabel_configs (
    id UUID PRIMARY KEY,
    reseller_id UUID REFERENCES reseller_accounts(id),
    logo_url VARCHAR(500),
    favicon_url VARCHAR(500),
    primary_color VARCHAR(7),
    secondary_color VARCHAR(7),
    company_name VARCHAR(255),
    support_email VARCHAR(255),
    custom_css TEXT,
    email_templates JSONB
);
```

**Frontend Changes:**
- New reseller dashboard at `/reseller`
- White-label theme provider that loads config from API
- Dynamic branding based on domain/subdomain
- Client management interface

**Key Features:**
- Custom domain support (CNAME mapping)
- Branded emails (SendGrid dynamic templates)
- Custom logo, colors, and favicon
- Commission tracking and payouts
- Client usage analytics
- Tiered commission rates based on volume

**Technical Considerations:**
- DNS verification for custom domains
- SSL certificate provisioning (Let's Encrypt)
- Subdomain routing in nginx/load balancer
- Email sender verification (SPF, DKIM)

---

### 2. Zapier/Make Integration

**Priority:** HIGH
**Estimated Effort:** 2-3 weeks
**Revenue Impact:** High (enterprise adoption)

#### Description
Connect chatbot conversations to 5000+ apps through Zapier and Make (Integromat), enabling automated workflows.

#### Implementation Details

**Webhook Events to Expose:**
```python
WEBHOOK_EVENTS = {
    'conversation.started': 'When a new conversation begins',
    'conversation.ended': 'When a conversation is completed',
    'message.received': 'When visitor sends a message',
    'message.sent': 'When bot responds',
    'lead.captured': 'When contact info is collected',
    'handoff.requested': 'When human handoff is triggered',
    'feedback.received': 'When visitor rates conversation',
    'goal.completed': 'When a conversion goal is achieved',
}
```

**Backend Implementation:**
```
apps/
├── integrations/
│   ├── models.py
│   │   ├── WebhookEndpoint (user-configured webhooks)
│   │   ├── WebhookDelivery (delivery logs)
│   │   └── IntegrationAuth (OAuth tokens for Zapier)
│   ├── views.py
│   │   ├── ZapierAuthAPI (OAuth2 flow)
│   │   ├── WebhookSubscriptionAPI
│   │   └── TriggerTestAPI
│   ├── tasks.py
│   │   └── deliver_webhook (async delivery with retries)
│   └── zapier/
│       ├── authentication.py
│       ├── triggers.py
│       └── actions.py
```

**Zapier App Structure:**
```javascript
// zapier-app/
├── authentication.js    // OAuth2 with refresh tokens
├── triggers/
│   ├── newConversation.js
│   ├── newLead.js
│   ├── newMessage.js
│   └── handoffRequested.js
├── actions/
│   ├── sendMessage.js   // Send message to conversation
│   ├── tagConversation.js
│   └── updateLead.js
├── searches/
│   ├── findConversation.js
│   └── findLead.js
└── index.js
```

**Webhook Payload Example:**
```json
{
    "event": "lead.captured",
    "timestamp": "2025-01-15T10:30:00Z",
    "chatbot_id": "uuid",
    "chatbot_name": "Support Bot",
    "conversation_id": "uuid",
    "data": {
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+1234567890",
        "company": "Acme Inc",
        "custom_fields": {},
        "conversation_summary": "Asked about pricing...",
        "source_url": "https://example.com/pricing"
    }
}
```

**Key Features:**
- OAuth2 authentication for Zapier
- Webhook subscriptions with retry logic
- Real-time triggers via webhooks
- Actions: send messages, update leads, tag conversations
- Searches: find conversations, lookup leads
- Test triggers for Zapier setup

**Technical Considerations:**
- Webhook delivery queue (Celery) with exponential backoff
- Signature verification for security
- Rate limiting per integration
- Delivery logs for debugging

---

### 3. Lead Capture & CRM Lite

**Priority:** CRITICAL
**Estimated Effort:** 3-4 weeks
**Revenue Impact:** Very High (core monetization)

#### Description
Built-in lead management system that captures, organizes, and notifies on high-intent conversations.

#### Implementation Details

**Database Schema:**
```sql
-- Leads table
CREATE TABLE leads (
    id UUID PRIMARY KEY,
    org_id UUID REFERENCES organizations(id),
    chatbot_id UUID REFERENCES chatbots(id),
    conversation_id UUID REFERENCES conversations(id),

    -- Contact info
    email VARCHAR(255),
    phone VARCHAR(50),
    name VARCHAR(255),
    company VARCHAR(255),

    -- Lead scoring
    score INTEGER DEFAULT 0,
    status ENUM('new', 'contacted', 'qualified', 'converted', 'lost'),
    priority ENUM('low', 'medium', 'high', 'urgent'),

    -- Enrichment
    source_url VARCHAR(500),
    utm_source VARCHAR(100),
    utm_medium VARCHAR(100),
    utm_campaign VARCHAR(100),
    ip_address INET,
    country VARCHAR(100),
    city VARCHAR(100),

    -- Custom fields
    custom_fields JSONB DEFAULT '{}',
    tags VARCHAR(50)[],

    -- Timestamps
    captured_at TIMESTAMP,
    last_activity_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Lead activities
CREATE TABLE lead_activities (
    id UUID PRIMARY KEY,
    lead_id UUID REFERENCES leads(id),
    activity_type ENUM('created', 'email_sent', 'note_added', 'status_changed', 'exported'),
    description TEXT,
    metadata JSONB,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Lead capture forms (configurable per chatbot)
CREATE TABLE lead_capture_configs (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    enabled BOOLEAN DEFAULT true,
    trigger_type ENUM('always', 'after_messages', 'on_exit_intent', 'manual'),
    trigger_after_messages INTEGER DEFAULT 3,

    -- Form fields
    fields JSONB DEFAULT '[
        {"name": "email", "type": "email", "required": true, "label": "Email"},
        {"name": "name", "type": "text", "required": false, "label": "Name"}
    ]',

    -- Messaging
    intro_message TEXT DEFAULT 'Before we continue, could you share your contact info?',
    success_message TEXT DEFAULT 'Thanks! How else can I help?',

    created_at TIMESTAMP DEFAULT NOW()
);

-- Notification preferences
CREATE TABLE lead_notifications (
    id UUID PRIMARY KEY,
    org_id UUID REFERENCES organizations(id),
    user_id UUID REFERENCES users(id),

    -- Channels
    email_enabled BOOLEAN DEFAULT true,
    slack_webhook_url VARCHAR(500),

    -- Filters
    min_score INTEGER DEFAULT 0,
    chatbot_ids UUID[],  -- null = all chatbots

    -- Frequency
    instant_notifications BOOLEAN DEFAULT true,
    daily_digest BOOLEAN DEFAULT false,
    digest_time TIME DEFAULT '09:00',

    created_at TIMESTAMP DEFAULT NOW()
);
```

**Backend Implementation:**
```
apps/
├── leads/
│   ├── models.py
│   ├── views.py
│   │   ├── LeadViewSet (CRUD + bulk actions)
│   │   ├── LeadCaptureConfigAPI
│   │   ├── LeadExportAPI
│   │   └── LeadAnalyticsAPI
│   ├── serializers.py
│   ├── filters.py (advanced filtering)
│   ├── scoring.py (lead scoring logic)
│   ├── notifications.py
│   │   ├── send_instant_notification()
│   │   ├── send_slack_notification()
│   │   └── send_daily_digest()
│   └── tasks.py
│       ├── process_new_lead
│       ├── enrich_lead_data (IP geolocation, company lookup)
│       └── send_digest_emails
```

**Lead Scoring Algorithm:**
```python
def calculate_lead_score(lead, conversation):
    score = 0

    # Contact completeness
    if lead.email: score += 20
    if lead.phone: score += 15
    if lead.company: score += 10
    if lead.name: score += 5

    # Engagement signals
    score += min(conversation.message_count * 2, 20)  # Up to 20 points
    score += min(conversation.duration_minutes, 15)   # Up to 15 points

    # Intent signals (from conversation analysis)
    high_intent_keywords = ['pricing', 'demo', 'buy', 'purchase', 'quote']
    if any(kw in conversation.transcript.lower() for kw in high_intent_keywords):
        score += 25

    # Source quality
    if lead.utm_source in ['google', 'linkedin']:
        score += 10

    return min(score, 100)
```

**Frontend Pages:**
```
/leads                    # Lead list with filters
/leads/:id                # Lead detail page
/leads/settings           # Capture form config
/leads/notifications      # Notification preferences
```

**Key Features:**
- Configurable lead capture forms
- Automatic lead scoring
- Email/Slack instant notifications
- Daily digest emails
- Lead export (CSV, Excel)
- Activity timeline per lead
- Bulk actions (tag, delete, export)
- UTM parameter tracking
- IP-based geolocation

---

### 4. Multi-Channel Deployment

**Priority:** HIGH
**Estimated Effort:** 6-8 weeks (per channel)
**Revenue Impact:** High (market expansion)

#### Description
Deploy chatbots across multiple messaging platforms beyond web embed.

#### Implementation Details

**Supported Channels:**

##### WhatsApp Business API
```
apps/
├── channels/
│   ├── whatsapp/
│   │   ├── client.py (WhatsApp Cloud API client)
│   │   ├── webhooks.py (message handling)
│   │   ├── templates.py (message template management)
│   │   └── media.py (image/document handling)
```

**WhatsApp Setup Flow:**
1. User connects WhatsApp Business account via Facebook OAuth
2. We store access token and phone number ID
3. Configure webhook URL in Meta dashboard
4. Map chatbot to WhatsApp number

**Message Handling:**
```python
@api_view(['POST'])
def whatsapp_webhook(request):
    # Verify webhook signature
    signature = request.headers.get('X-Hub-Signature-256')
    if not verify_signature(request.body, signature):
        return Response(status=403)

    # Process incoming message
    for entry in request.data.get('entry', []):
        for change in entry.get('changes', []):
            if change['field'] == 'messages':
                message = change['value']['messages'][0]
                phone_number = message['from']
                text = message.get('text', {}).get('body', '')

                # Find or create conversation
                conversation = get_or_create_whatsapp_conversation(phone_number)

                # Get bot response
                response = process_message(conversation.chatbot, text, conversation)

                # Send response via WhatsApp
                send_whatsapp_message(phone_number, response)

    return Response(status=200)
```

##### Facebook Messenger
```python
# Similar structure to WhatsApp
# Uses Facebook Graph API
# Requires Facebook Page connection
```

##### Slack
```python
# Slack Bot implementation
# Uses Slack Bolt framework
# Supports slash commands and mentions
```

##### Discord
```python
# Discord.py bot
# Runs as separate service
# Connects via Discord Gateway
```

**Channel Configuration Model:**
```sql
CREATE TABLE channel_configs (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    channel_type ENUM('web', 'whatsapp', 'messenger', 'slack', 'discord', 'instagram'),

    -- Channel-specific credentials
    credentials JSONB,  -- Encrypted

    -- Status
    is_active BOOLEAN DEFAULT false,
    verified_at TIMESTAMP,

    -- Settings
    settings JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT NOW()
);
```

**Key Features per Channel:**

| Feature | Web | WhatsApp | Messenger | Slack | Discord |
|---------|-----|----------|-----------|-------|---------|
| Rich text | Yes | Limited | Yes | Yes | Yes |
| Images | Yes | Yes | Yes | Yes | Yes |
| Buttons | Yes | Yes | Yes | Yes | Yes |
| Carousels | Yes | No | Yes | No | No |
| Quick replies | Yes | Yes | Yes | No | No |
| File upload | Yes | Yes | Yes | Yes | Yes |

---

### 5. AI Agent Actions

**Priority:** HIGH
**Estimated Effort:** 4-6 weeks
**Revenue Impact:** Very High (premium feature)

#### Description
Transform chatbots from Q&A systems into business automation agents that can take actions.

#### Implementation Details

**Supported Actions:**

##### Appointment Booking (Calendly/Cal.com)
```python
class CalendlyAction:
    """Book appointments via Calendly API"""

    def get_available_slots(self, event_type_id: str, date_range: tuple):
        """Fetch available time slots"""
        pass

    def create_booking(self, event_type_id: str, invitee_email: str, slot: datetime):
        """Create a booking"""
        pass

    def cancel_booking(self, booking_id: str):
        """Cancel existing booking"""
        pass
```

##### Payment Processing (Stripe)
```python
class StripeAction:
    """Process payments via Stripe"""

    def create_payment_link(self, amount: int, currency: str, description: str):
        """Generate a payment link"""
        pass

    def create_checkout_session(self, line_items: list, success_url: str):
        """Create Stripe Checkout session"""
        pass

    def check_payment_status(self, session_id: str):
        """Check if payment completed"""
        pass
```

##### Support Tickets (Zendesk/Freshdesk)
```python
class ZendeskAction:
    """Create support tickets"""

    def create_ticket(self, subject: str, description: str, requester_email: str):
        """Create a new ticket"""
        pass

    def add_comment(self, ticket_id: str, comment: str):
        """Add comment to existing ticket"""
        pass
```

##### Custom Webhooks
```python
class WebhookAction:
    """Call custom webhook endpoints"""

    def execute(self, url: str, method: str, payload: dict, headers: dict):
        """Execute webhook with conversation data"""
        pass
```

**Action Configuration:**
```sql
CREATE TABLE chatbot_actions (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    action_type ENUM('calendly', 'stripe', 'zendesk', 'freshdesk', 'webhook', 'email', 'slack'),
    name VARCHAR(100),
    description TEXT,  -- Used by AI to decide when to trigger

    -- Configuration
    config JSONB,  -- Action-specific settings
    credentials JSONB,  -- Encrypted API keys

    -- Trigger conditions
    trigger_phrases TEXT[],  -- Keywords that may trigger this action
    requires_confirmation BOOLEAN DEFAULT true,

    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**AI Action Selection (LLM-based):**
```python
def select_action(message: str, conversation: Conversation, available_actions: list):
    """Use LLM to determine if an action should be triggered"""

    action_descriptions = "\n".join([
        f"- {a.name}: {a.description}" for a in available_actions
    ])

    prompt = f"""
    Based on the user's message and conversation context, determine if any action should be triggered.

    Available actions:
    {action_descriptions}

    User message: {message}

    Respond with JSON:
    {{"action": "action_name or null", "parameters": {{}}, "confirmation_message": "string"}}
    """

    response = llm.complete(prompt)
    return parse_action_response(response)
```

**Frontend Action Builder:**
- Visual action configuration
- Test action execution
- Action analytics (trigger count, success rate)
- Conditional logic builder

---

## Retention & Stickiness Features

### 6. Conversation Analytics Dashboard

**Priority:** MEDIUM
**Estimated Effort:** 2-3 weeks
**Revenue Impact:** Medium (reduces churn)

#### Description
Comprehensive analytics showing conversation patterns, content gaps, and optimization opportunities.

#### Implementation Details

**Analytics Metrics:**
```python
ANALYTICS_METRICS = {
    # Volume metrics
    'total_conversations': 'COUNT(*)',
    'total_messages': 'SUM(message_count)',
    'unique_visitors': 'COUNT(DISTINCT visitor_id)',

    # Engagement metrics
    'avg_conversation_length': 'AVG(message_count)',
    'avg_duration_seconds': 'AVG(duration_seconds)',
    'bounce_rate': 'COUNT(message_count=1) / COUNT(*)',

    # Satisfaction metrics
    'avg_rating': 'AVG(rating)',
    'positive_feedback_rate': 'COUNT(rating>=4) / COUNT(rating)',

    # Resolution metrics
    'handoff_rate': 'COUNT(handoff_requested) / COUNT(*)',
    'goal_completion_rate': 'COUNT(goal_completed) / COUNT(*)',
}
```

**Content Gap Analysis:**
```python
def analyze_content_gaps(chatbot_id: str, date_range: tuple):
    """Identify questions the bot couldn't answer well"""

    # Get low-confidence responses
    low_confidence = Message.objects.filter(
        conversation__chatbot_id=chatbot_id,
        is_bot=True,
        confidence_score__lt=0.6,
        created_at__range=date_range
    ).select_related('conversation')

    # Cluster similar questions
    questions = [m.conversation.messages.filter(is_bot=False).last().content
                 for m in low_confidence]
    clusters = cluster_questions(questions)

    return {
        'total_gaps': len(low_confidence),
        'clusters': clusters,
        'suggested_content': generate_content_suggestions(clusters)
    }
```

**Dashboard Components:**
```
/analytics
├── Overview (key metrics cards)
├── Conversation Volume (line chart over time)
├── Peak Hours Heatmap (hour x day)
├── Top Questions (ranked list)
├── Content Gaps (unanswered questions)
├── Sentiment Analysis (pie chart)
├── Geographic Distribution (map)
└── Funnel Analysis (conversation → lead → conversion)
```

**Database Additions:**
```sql
-- Pre-aggregated analytics for fast queries
CREATE TABLE analytics_daily (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    date DATE,

    conversations_count INTEGER,
    messages_count INTEGER,
    unique_visitors INTEGER,
    avg_duration_seconds FLOAT,
    avg_messages_per_conversation FLOAT,
    handoff_count INTEGER,
    leads_captured INTEGER,
    avg_rating FLOAT,

    -- Hourly breakdown
    hourly_conversations INTEGER[24],

    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(chatbot_id, date)
);

-- Question clusters for content gap analysis
CREATE TABLE question_clusters (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    cluster_label VARCHAR(255),
    sample_questions TEXT[],
    occurrence_count INTEGER,
    avg_confidence FLOAT,
    suggested_content TEXT,
    is_addressed BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### 7. A/B Testing for Chatbot Personas

**Priority:** MEDIUM
**Estimated Effort:** 2-3 weeks
**Revenue Impact:** Medium (optimization tool)

#### Description
Test different chatbot personalities, tones, and configurations to optimize conversion rates.

#### Implementation Details

**Database Schema:**
```sql
CREATE TABLE ab_experiments (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    name VARCHAR(255),
    description TEXT,

    -- Experiment config
    traffic_split JSONB,  -- {"control": 50, "variant_a": 25, "variant_b": 25}

    -- Status
    status ENUM('draft', 'running', 'paused', 'completed'),
    started_at TIMESTAMP,
    ended_at TIMESTAMP,

    -- Winner
    winning_variant_id UUID,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE ab_variants (
    id UUID PRIMARY KEY,
    experiment_id UUID REFERENCES ab_experiments(id),
    name VARCHAR(100),  -- "control", "variant_a", etc.

    -- What's being tested
    config_overrides JSONB,  -- Overrides to chatbot config

    -- Metrics
    conversations_count INTEGER DEFAULT 0,
    leads_captured INTEGER DEFAULT 0,
    avg_rating FLOAT,
    goal_completions INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Track which variant each conversation used
ALTER TABLE conversations ADD COLUMN ab_variant_id UUID REFERENCES ab_variants(id);
```

**Variant Assignment:**
```python
def assign_variant(visitor_id: str, experiment: ABExperiment):
    """Deterministically assign visitor to variant"""

    # Use consistent hashing for same visitor = same variant
    hash_input = f"{visitor_id}:{experiment.id}"
    hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 100

    cumulative = 0
    for variant_id, percentage in experiment.traffic_split.items():
        cumulative += percentage
        if hash_value < cumulative:
            return variant_id

    return list(experiment.traffic_split.keys())[0]  # Fallback to first
```

**Testable Elements:**
- System prompt / persona
- Greeting message
- Response tone (formal/casual)
- Lead capture timing
- Follow-up questions
- Button/quick reply options

---

### 8. Team Collaboration

**Priority:** MEDIUM
**Estimated Effort:** 2-3 weeks
**Revenue Impact:** Medium (enterprise requirement)

#### Description
Multi-user access with role-based permissions for team collaboration.

#### Implementation Details

**Database Schema:**
```sql
-- Already have organizations, add team members
CREATE TABLE organization_members (
    id UUID PRIMARY KEY,
    org_id UUID REFERENCES organizations(id),
    user_id UUID REFERENCES users(id),

    role ENUM('owner', 'admin', 'editor', 'viewer'),

    -- Granular permissions
    permissions JSONB DEFAULT '{
        "chatbots": {"create": true, "edit": true, "delete": false},
        "leads": {"view": true, "export": true, "delete": false},
        "analytics": {"view": true},
        "settings": {"view": true, "edit": false},
        "billing": {"view": false, "manage": false},
        "team": {"view": true, "manage": false}
    }',

    invited_by UUID REFERENCES users(id),
    invited_at TIMESTAMP,
    accepted_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, user_id)
);

-- Conversation comments/notes
CREATE TABLE conversation_comments (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    user_id UUID REFERENCES users(id),
    content TEXT,

    -- For @mentions
    mentioned_users UUID[],

    created_at TIMESTAMP DEFAULT NOW()
);

-- Activity feed
CREATE TABLE team_activities (
    id UUID PRIMARY KEY,
    org_id UUID REFERENCES organizations(id),
    user_id UUID REFERENCES users(id),

    activity_type VARCHAR(50),
    description TEXT,
    target_type VARCHAR(50),
    target_id UUID,
    metadata JSONB,

    created_at TIMESTAMP DEFAULT NOW()
);
```

**Permission Decorator:**
```python
def require_permission(resource: str, action: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            member = OrganizationMember.objects.get(
                org_id=request.org.id,
                user_id=request.user.id
            )

            if not member.has_permission(resource, action):
                raise PermissionDenied(f"Missing permission: {resource}.{action}")

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

# Usage
@require_permission('chatbots', 'edit')
def update_chatbot(request, chatbot_id):
    ...
```

**Frontend Features:**
- Team members page with invite flow
- Role assignment dropdown
- Activity feed sidebar
- @mention in conversation comments
- Permission-based UI hiding

---

## Competitive Moat Features

### 9. Human Handoff

**Priority:** HIGH
**Estimated Effort:** 4-5 weeks
**Revenue Impact:** High (key differentiator)

#### Description
Seamless transition from AI chatbot to human agents when needed.

#### Implementation Details

**Database Schema:**
```sql
-- Handoff requests
CREATE TABLE handoff_requests (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    chatbot_id UUID REFERENCES chatbots(id),
    org_id UUID REFERENCES organizations(id),

    -- Request details
    reason ENUM('user_requested', 'low_confidence', 'sentiment_negative', 'keyword_trigger'),
    trigger_message TEXT,
    ai_summary TEXT,  -- AI-generated conversation summary

    -- Status
    status ENUM('pending', 'accepted', 'completed', 'abandoned', 'timeout'),
    priority ENUM('low', 'normal', 'high', 'urgent'),

    -- Assignment
    assigned_to UUID REFERENCES users(id),
    assigned_at TIMESTAMP,

    -- Timing
    requested_at TIMESTAMP DEFAULT NOW(),
    first_response_at TIMESTAMP,
    resolved_at TIMESTAMP,

    -- Metrics
    wait_time_seconds INTEGER,
    handle_time_seconds INTEGER,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Agent availability
CREATE TABLE agent_availability (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    org_id UUID REFERENCES organizations(id),

    is_online BOOLEAN DEFAULT false,
    status ENUM('available', 'busy', 'away'),

    -- Capacity
    max_concurrent_chats INTEGER DEFAULT 5,
    current_chat_count INTEGER DEFAULT 0,

    -- Assignment rules
    chatbot_ids UUID[],  -- Which chatbots this agent handles

    last_seen_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Agent settings
CREATE TABLE handoff_settings (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),

    enabled BOOLEAN DEFAULT true,

    -- Triggers
    allow_user_request BOOLEAN DEFAULT true,
    user_request_keywords TEXT[] DEFAULT ARRAY['human', 'agent', 'person', 'talk to someone'],
    auto_handoff_on_low_confidence BOOLEAN DEFAULT false,
    confidence_threshold FLOAT DEFAULT 0.4,
    auto_handoff_on_negative_sentiment BOOLEAN DEFAULT false,

    -- Queue settings
    max_wait_time_seconds INTEGER DEFAULT 300,
    offline_message TEXT DEFAULT 'Our team is currently offline. Please leave your email and we''ll get back to you.',

    -- Business hours
    business_hours JSONB,  -- {"monday": {"start": "09:00", "end": "17:00"}, ...}
    timezone VARCHAR(50) DEFAULT 'UTC',

    created_at TIMESTAMP DEFAULT NOW()
);
```

**Real-time Implementation (WebSocket):**
```python
# consumers.py (Django Channels)
class HandoffConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        self.org_id = self.scope['org_id']

        # Join agent's personal channel
        await self.channel_layer.group_add(
            f"agent_{self.user.id}",
            self.channel_name
        )

        # Join org-wide handoff channel
        await self.channel_layer.group_add(
            f"handoffs_{self.org_id}",
            self.channel_name
        )

        await self.accept()

        # Update agent status
        await self.set_agent_online()

    async def receive_json(self, content):
        action = content.get('action')

        if action == 'accept_handoff':
            await self.accept_handoff(content['handoff_id'])
        elif action == 'send_message':
            await self.send_agent_message(content)
        elif action == 'complete_handoff':
            await self.complete_handoff(content['handoff_id'])
        elif action == 'update_status':
            await self.update_status(content['status'])

    async def handoff_requested(self, event):
        """New handoff request notification"""
        await self.send_json({
            'type': 'new_handoff',
            'handoff': event['handoff']
        })

    async def visitor_message(self, event):
        """Forward visitor message to agent"""
        await self.send_json({
            'type': 'visitor_message',
            'conversation_id': event['conversation_id'],
            'message': event['message']
        })
```

**Handoff Trigger Logic:**
```python
def check_handoff_triggers(conversation: Conversation, message: str, bot_response: dict):
    settings = conversation.chatbot.handoff_settings

    if not settings.enabled:
        return None

    # Check user request
    if settings.allow_user_request:
        if any(kw in message.lower() for kw in settings.user_request_keywords):
            return create_handoff_request(conversation, 'user_requested', message)

    # Check confidence
    if settings.auto_handoff_on_low_confidence:
        if bot_response.get('confidence', 1.0) < settings.confidence_threshold:
            return create_handoff_request(conversation, 'low_confidence', message)

    # Check sentiment
    if settings.auto_handoff_on_negative_sentiment:
        sentiment = analyze_sentiment(message)
        if sentiment < -0.5:
            return create_handoff_request(conversation, 'sentiment_negative', message)

    return None
```

**Agent Dashboard:**
- Real-time queue view
- Active conversations panel
- Conversation history + AI summary
- Canned responses library
- Agent performance metrics

---

### 10. Custom Training / Fine-tuning

**Priority:** MEDIUM
**Estimated Effort:** 3-4 weeks
**Revenue Impact:** High (enterprise stickiness)

#### Description
Allow users to upload custom documents and train on historical support data.

#### Implementation Details

**Supported Document Types:**
- PDF documents
- Word documents (.docx)
- Excel spreadsheets (.xlsx)
- CSV files
- Plain text files
- Markdown files
- HTML pages

**Database Schema:**
```sql
CREATE TABLE training_documents (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),
    org_id UUID REFERENCES organizations(id),

    -- File info
    filename VARCHAR(255),
    file_type VARCHAR(50),
    file_size INTEGER,
    file_url VARCHAR(500),  -- S3 URL

    -- Processing status
    status ENUM('pending', 'processing', 'completed', 'failed'),
    error_message TEXT,

    -- Extracted content
    page_count INTEGER,
    chunk_count INTEGER,

    -- Metadata
    title VARCHAR(255),
    description TEXT,
    tags VARCHAR(50)[],

    uploaded_by UUID REFERENCES users(id),
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Support ticket import for training
CREATE TABLE training_tickets (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),

    -- Ticket data
    question TEXT,
    answer TEXT,
    category VARCHAR(100),

    -- Quality signals
    rating INTEGER,  -- Customer satisfaction rating
    resolution_time_hours FLOAT,

    -- Source
    source ENUM('zendesk', 'freshdesk', 'intercom', 'csv_import'),
    external_id VARCHAR(255),

    -- Processing
    is_processed BOOLEAN DEFAULT false,
    embedding_id VARCHAR(255),

    created_at TIMESTAMP DEFAULT NOW()
);
```

**Document Processing Pipeline:**
```python
@celery.task
def process_training_document(document_id: str):
    document = TrainingDocument.objects.get(id=document_id)

    try:
        document.status = 'processing'
        document.save()

        # Download file
        file_content = download_from_s3(document.file_url)

        # Extract text based on file type
        if document.file_type == 'pdf':
            pages = extract_pdf_text(file_content)
        elif document.file_type == 'docx':
            pages = extract_docx_text(file_content)
        elif document.file_type == 'csv':
            pages = extract_csv_qa_pairs(file_content)
        # ... other types

        # Chunk content
        chunks = chunk_content(pages, chunk_size=500, overlap=50)

        # Generate embeddings and store in Pinecone
        namespace = f"docs_{document.chatbot_id}"
        embed_and_store(chunks, namespace, metadata={'source': document.id})

        document.status = 'completed'
        document.chunk_count = len(chunks)
        document.page_count = len(pages)
        document.processed_at = timezone.now()
        document.save()

    except Exception as e:
        document.status = 'failed'
        document.error_message = str(e)
        document.save()
        raise
```

**Zendesk Import:**
```python
class ZendeskImporter:
    def __init__(self, subdomain: str, api_token: str, email: str):
        self.client = Zendesk(subdomain, email, api_token)

    def import_tickets(self, chatbot_id: str, filters: dict):
        """Import resolved tickets for training"""

        tickets = self.client.tickets.list(
            status='solved',
            created_after=filters.get('after'),
            tags=filters.get('tags')
        )

        for ticket in tickets:
            # Get the question (first customer message)
            comments = self.client.tickets.comments(ticket.id)
            question = next(c for c in comments if not c.is_agent)

            # Get the answer (agent response)
            answer = next(c for c in comments if c.is_agent)

            TrainingTicket.objects.create(
                chatbot_id=chatbot_id,
                question=question.body,
                answer=answer.body,
                category=ticket.tags[0] if ticket.tags else None,
                rating=ticket.satisfaction_rating,
                source='zendesk',
                external_id=ticket.id
            )
```

---

### 11. Multilingual Support

**Priority:** MEDIUM
**Estimated Effort:** 2-3 weeks
**Revenue Impact:** High (global market)

#### Description
Automatic language detection and response translation for global audiences.

#### Implementation Details

**Language Detection:**
```python
from langdetect import detect, detect_langs

def detect_language(text: str) -> tuple[str, float]:
    """Detect language and confidence"""
    try:
        langs = detect_langs(text)
        return langs[0].lang, langs[0].prob
    except:
        return 'en', 1.0  # Default to English
```

**Translation Service:**
```python
class TranslationService:
    def __init__(self):
        self.client = GoogleTranslateClient()  # or DeepL
        self.cache = RedisCache()

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        # Check cache first
        cache_key = f"trans:{source_lang}:{target_lang}:{hash(text)}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Translate
        result = self.client.translate(text, source=source_lang, target=target_lang)

        # Cache for 24 hours
        self.cache.set(cache_key, result, ttl=86400)

        return result
```

**Message Flow with Translation:**
```python
def process_message_multilingual(chatbot: Chatbot, message: str, conversation: Conversation):
    settings = chatbot.multilingual_settings

    if not settings.enabled:
        return process_message(chatbot, message, conversation)

    # Detect visitor language
    visitor_lang, confidence = detect_language(message)

    if confidence < 0.8:
        visitor_lang = conversation.detected_language or settings.default_language

    # Store detected language
    conversation.detected_language = visitor_lang
    conversation.save()

    # Translate to bot's native language for processing
    native_lang = settings.native_language  # e.g., 'en'

    if visitor_lang != native_lang:
        translated_message = translation_service.translate(
            message, visitor_lang, native_lang
        )
    else:
        translated_message = message

    # Get bot response (in native language)
    response = process_message(chatbot, translated_message, conversation)

    # Translate response back to visitor's language
    if visitor_lang != native_lang:
        response['content'] = translation_service.translate(
            response['content'], native_lang, visitor_lang
        )

    return response
```

**Configuration:**
```sql
CREATE TABLE multilingual_settings (
    id UUID PRIMARY KEY,
    chatbot_id UUID REFERENCES chatbots(id),

    enabled BOOLEAN DEFAULT false,
    native_language VARCHAR(10) DEFAULT 'en',

    -- Supported languages
    supported_languages VARCHAR(10)[] DEFAULT ARRAY['en'],
    auto_detect BOOLEAN DEFAULT true,

    -- Translation provider
    provider ENUM('google', 'deepl', 'azure'),

    -- UI customization
    show_language_selector BOOLEAN DEFAULT false,

    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Quick Wins

### 12. Embeddable ROI Calculator

**Priority:** LOW
**Estimated Effort:** 1 week
**Revenue Impact:** Medium (conversion tool)

#### Description
Interactive calculator showing potential savings from using AI chatbots.

#### Implementation
```jsx
// ROICalculator.jsx
const ROICalculator = () => {
  const [inputs, setInputs] = useState({
    monthlyTickets: 1000,
    avgHandleTime: 15,  // minutes
    agentHourlyRate: 25,
    resolutionRate: 60,  // % AI can handle
  });

  const results = useMemo(() => {
    const ticketsHandledByAI = inputs.monthlyTickets * (inputs.resolutionRate / 100);
    const hoursPerMonth = (ticketsHandledByAI * inputs.avgHandleTime) / 60;
    const monthlySavings = hoursPerMonth * inputs.agentHourlyRate;
    const yearlySavings = monthlySavings * 12;

    return {
      ticketsAutomated: ticketsHandledByAI,
      hoursPerMonth,
      monthlySavings,
      yearlySavings,
      roi: ((yearlySavings - 2400) / 2400 * 100)  // Assuming $200/mo cost
    };
  }, [inputs]);

  return (
    <div className="roi-calculator">
      {/* Input sliders */}
      {/* Results display */}
    </div>
  );
};
```

---

### 13. Public Template Gallery

**Priority:** LOW
**Estimated Effort:** 1-2 weeks
**Revenue Impact:** Medium (acquisition + SEO)

#### Description
Pre-built chatbot templates for common industries and use cases.

#### Implementation

**Database Schema:**
```sql
CREATE TABLE chatbot_templates (
    id UUID PRIMARY KEY,

    -- Template info
    name VARCHAR(255),
    slug VARCHAR(100) UNIQUE,
    description TEXT,
    long_description TEXT,

    -- Categorization
    category ENUM('ecommerce', 'saas', 'healthcare', 'realestate', 'education', 'other'),
    tags VARCHAR(50)[],

    -- Template content
    system_prompt TEXT,
    greeting_message TEXT,
    sample_questions TEXT[],
    suggested_responses JSONB,

    -- Visuals
    thumbnail_url VARCHAR(500),
    preview_conversation JSONB,

    -- Stats
    use_count INTEGER DEFAULT 0,
    avg_rating FLOAT,

    -- Status
    is_published BOOLEAN DEFAULT false,
    is_featured BOOLEAN DEFAULT false,

    created_at TIMESTAMP DEFAULT NOW()
);
```

**Template Categories:**
- E-commerce (product recommendations, order tracking)
- SaaS (feature questions, pricing, onboarding)
- Healthcare (appointment booking, FAQ)
- Real Estate (property inquiries, scheduling tours)
- Education (course info, enrollment)
- Customer Support (general FAQ, ticket creation)
- Lead Generation (qualification, demo booking)

---

### 14. Slack Community

**Priority:** LOW
**Estimated Effort:** 1 week (setup)
**Revenue Impact:** Medium (retention + feedback)

#### Description
Build a user community for support, feedback, and feature requests.

#### Implementation
- Set up Slack workspace with channels:
  - `#general` - General discussion
  - `#support` - Technical help
  - `#feature-requests` - Ideas and voting
  - `#showcase` - User success stories
  - `#announcements` - Product updates
- Add Slack join link to app dashboard
- Create welcome bot with onboarding flow
- Set up integration with feedback system

---

## Implementation Timeline

### Phase 1: Foundation (Immediate Priority)
1. **Lead Capture & CRM Lite** - Core monetization feature
2. **Human Handoff** - Key differentiator
3. **Zapier Integration** - Enterprise adoption

### Phase 2: Growth (Next Priority)
4. **Multi-Channel (WhatsApp first)** - Market expansion
5. **AI Agent Actions** - Premium feature
6. **Team Collaboration** - Enterprise requirement

### Phase 3: Optimization
7. **Conversation Analytics Dashboard** - Retention
8. **A/B Testing** - Optimization
9. **Multilingual Support** - Global expansion

### Phase 4: Scale
10. **White-Label Program** - Channel distribution
11. **Custom Training** - Enterprise stickiness
12. **Template Gallery** - Acquisition + SEO

---

## Technical Dependencies

### Infrastructure Requirements
- **Redis** - Caching, real-time features, rate limiting
- **WebSocket Server** - Human handoff, live updates
- **Celery Workers** - Background processing, webhooks
- **S3/Cloud Storage** - Document uploads
- **Translation API** - Google Cloud or DeepL

### Third-Party Integrations
- **Zapier** - Partner application required
- **Stripe** - Payment processing
- **Calendly** - Appointment booking
- **Zendesk/Freshdesk** - Ticket creation
- **WhatsApp Business API** - Meta verification required
- **Slack API** - Bot creation

### Security Considerations
- Encrypt all API credentials at rest
- Webhook signature verification
- Rate limiting on all integrations
- Audit logging for sensitive actions
- GDPR compliance for EU users

---

## Success Metrics

| Feature | Primary Metric | Target |
|---------|---------------|--------|
| Lead Capture | Leads captured/month | +50% conversations → leads |
| Zapier | Integration activations | 30% of paid users |
| Human Handoff | CSAT after handoff | > 4.5/5 |
| Multi-Channel | Channel distribution | 25% non-web |
| A/B Testing | Experiments run | 2+ per active user |
| Templates | Template usage | 40% of new chatbots |

---

*Document last updated: January 2025*
*Next review: Quarterly*
