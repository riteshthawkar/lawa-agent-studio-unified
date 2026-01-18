# Analytics & Leads Documentation

> Complete documentation of all analytics, metrics, and lead scoring features in Lawa Agent Studio.

---

## Table of Contents

1. [Overview](#overview)
2. [Analytics Page](#analytics-page)
   - [Stats Cards](#analytics-stats-cards)
   - [Smart Insights](#smart-insights)
   - [Activity Charts](#activity-charts)
   - [Query Analytics](#query-analytics)
   - [Citation Analytics](#citation-analytics)
   - [Geographic Analytics](#geographic-analytics)
   - [Traffic Insights](#traffic-insights)
   - [Feedback Details](#feedback-details)
   - [Indexing Health](#indexing-health)
3. [Leads Page](#leads-page)
   - [View Modes](#view-modes)
   - [Lead Stats Cards](#lead-stats-cards)
   - [Lead Charts](#lead-charts)
   - [Lead Table](#lead-table)
   - [Lead Detail Dialog](#lead-detail-dialog)
4. [Visitor Insights Mode](#visitor-insights-mode)
   - [Engagement Stats](#engagement-stats)
   - [Visitor Charts](#visitor-charts)
   - [Common Questions](#common-questions)
5. [Lead Scoring System](#lead-scoring-system)
   - [Score Components](#score-components)
   - [Priority Classification](#priority-classification)
   - [AI/LLM Analysis](#aillm-analysis)
6. [Weekly Email Reports](#weekly-email-reports)
7. [Tier-Based Features](#tier-based-features)
8. [API Reference](#api-reference)

---

## Overview

Lawa Agent Studio provides comprehensive analytics and lead intelligence to help users understand:

- **How visitors interact** with their chatbots
- **What questions** are being asked
- **Who are the high-intent visitors** (leads)
- **Content gaps** that need addressing
- **Performance metrics** for optimization

The system supports two primary user personas:
1. **Business/Sales Users** - Focus on lead generation and sales opportunities
2. **Individual Users** (Researchers, Professors, Personal Sites) - Focus on visitor engagement and content insights

---

## Analytics Page

The Analytics page provides comprehensive insights into chatbot performance and user engagement.

### Analytics Stats Cards

| Metric | Description | Data Source | Calculation |
|--------|-------------|-------------|-------------|
| **Total Queries** | Total number of questions asked to the chatbot | `ChatMessage` model (role='user') | `COUNT(*)` of user messages |
| **Sessions** | Total number of chat sessions | `ChatSession` model | `COUNT(*)` of sessions |
| **Queries per Session** | Average questions per conversation | Derived | `total_queries / total_sessions` |
| **Satisfaction Score** | Percentage of positive feedback | `ChatFeedback` model | `(likes / (likes + dislikes)) * 100` |
| **Response Time** | Average time to generate responses | `ChatMessage.latency_ms` | `AVG(latency_ms)` for assistant messages |
| **Feedback Rate** | Percentage of conversations with feedback | Derived | `(sessions_with_feedback / total_sessions) * 100` |
| **Avg Session Time** | Average duration of conversations | `ChatSession` model | `AVG(last_activity - started_at)` |

**What Users Learn:**
- High queries per session indicates engaged users
- Satisfaction score above 80% is considered excellent
- Response time under 2 seconds is optimal
- Low feedback rate may indicate users aren't prompted to give feedback

---

### Smart Insights

Visual insights cards that provide at-a-glance performance indicators.

| Insight | Good | Warning | Danger |
|---------|------|---------|--------|
| **Satisfaction** | ≥80% | 60-79% | <60% |
| **Engagement** | ≥3 queries/session | 1.5-2.9 | <1.5 |
| **Response Time** | ≤2 seconds | 2-5 seconds | >5 seconds |
| **Feedback Rate** | ≥30% | 10-29% | <10% |

**Additional Insights:**
- **Peak Hour**: Hour with most activity (from hourly data)
- **Busiest Day**: Day of week with most activity (from weekly data)

---

### Activity Charts

#### 1. Activity Trend (Area Chart)
- **What it shows**: Daily query volume over time
- **Data source**: `ChatMessage` aggregated by date
- **Calculation**: `COUNT(*)` grouped by `DATE(created_at)`
- **User insight**: Identify trends, seasonal patterns, and growth

#### 2. Hourly Activity (Bar Chart) - Premium
- **What it shows**: Query distribution across 24 hours
- **Data source**: `ChatMessage` aggregated by hour
- **Calculation**: `COUNT(*)` grouped by `HOUR(created_at)`
- **User insight**: Identify peak usage times for staffing or maintenance windows

#### 3. Weekly Activity (Bar Chart) - Premium
- **What it shows**: Query distribution across days of the week
- **Data source**: `ChatMessage` aggregated by day of week
- **Calculation**: `COUNT(*)` grouped by `DAYOFWEEK(created_at)`
- **User insight**: Understand weekday vs weekend patterns

#### 4. Feedback Distribution (Pie Chart)
- **What it shows**: Ratio of positive to negative feedback
- **Data source**: `ChatFeedback` model
- **Calculation**: `COUNT(*)` grouped by `feedback_type`
- **User insight**: Overall user satisfaction at a glance

---

### Query Analytics

Detailed analysis of what users are asking.

| Metric | Description | Calculation |
|--------|-------------|-------------|
| **Total Queries** | All questions asked | `COUNT(*)` of user messages |
| **Unique Queries** | Distinct questions | `COUNT(DISTINCT content)` |
| **Repeat Rate** | How often same questions repeat | `((total - unique) / total) * 100` |
| **Avg Query Length** | Average characters per question | `AVG(LENGTH(content))` |

#### Top Queries
- Shows most frequently asked questions
- Ranked by occurrence count
- Visual ranking badges for top 3
- **Tier limits**: Basic (5), Premium (20), Enterprise (unlimited)

#### Query Categories - Premium
Categories are determined by keyword matching or LLM classification:

| Category | Keywords/Patterns |
|----------|-------------------|
| How-To | "how to", "how do", "how can" |
| What Is | "what is", "what are", "define" |
| Pricing | "price", "cost", "pricing", "$" |
| Support | "help", "issue", "problem", "error" |
| Features | "feature", "can it", "does it" |
| Other | Everything else |

#### Unanswered Questions
- Questions that received negative feedback (thumbs down)
- Indicates content gaps in knowledge base
- **Action**: Add missing information to improve responses

---

### Citation Analytics

Analysis of which knowledge base pages are being referenced in responses.

| Metric | Description | Calculation |
|--------|-------------|-------------|
| **Total Citations** | All page references in responses | `COUNT(*)` of citations |
| **Unique Pages Cited** | Distinct pages referenced | `COUNT(DISTINCT page_url)` |
| **Avg Citations/Response** | Pages referenced per answer | `total_citations / responses_with_citations` |
| **Responses with Citations** | Answers that include sources | `COUNT(*)` where citations > 0 |

#### Top Cited Pages
- Most frequently referenced knowledge base pages
- **User insight**: Identifies most valuable content
- **Tier limits**: Basic (10), Premium+ (unlimited)

---

### Geographic Analytics

Understand where your visitors are located.

| Metric | Description | Calculation |
|--------|-------------|-------------|
| **Total Sessions** | Sessions with geo data | `COUNT(*)` where geo_location is not null |
| **Countries** | Number of unique countries | `COUNT(DISTINCT country)` |
| **Top Country** | Country with most sessions | `MAX(count)` by country |
| **Geo Coverage** | % of sessions with location | `(sessions_with_geo / total_sessions) * 100` |

**Data Collection**: Geographic data is derived from IP addresses using GeoIP lookup.

---

### Traffic Insights

Understand how users access your chatbot.

#### Device Breakdown (Pie Chart)
| Device Type | Description |
|-------------|-------------|
| Desktop | Traditional computers |
| Mobile | Smartphones |
| Tablet | Tablets and iPads |

**User insight**: Optimize chatbot UI for primary device type.

#### Top Referrers
- Source URLs that drive traffic to the chatbot
- Shows which pages generate most conversations
- **User insight**: Place chatbot prominently on high-traffic pages

---

### Feedback Details

Detailed view of individual feedback entries.

| Field | Description |
|-------|-------------|
| **Question** | User's original question |
| **Response** | Chatbot's answer |
| **Feedback Type** | Like or Dislike |
| **Timestamp** | When feedback was given |
| **Chatbot** | Which chatbot received feedback |
| **Latency** | Response generation time (ms) |

**Filtering**: View all feedback, only likes, or only dislikes.

**User insight**: Review negative feedback to identify improvement areas.

---

### Indexing Health

Monitor the status of your knowledge base indexing.

| Metric | Description | Status Thresholds |
|--------|-------------|-------------------|
| **Total Pages** | Pages discovered for indexing | - |
| **Indexed Pages** | Successfully indexed | - |
| **Failed Pages** | Failed to index | - |
| **Success Rate** | % successfully indexed | Healthy ≥90%, Warning 70-89%, Critical <70% |

**User insight**: Failed pages won't be available for chatbot responses. Re-index or fix content issues.

---

## Leads Page

The Leads page helps identify and track high-intent visitors who may become customers or engaged community members.

### View Modes

The leads page supports two viewing modes:

| Mode | Target User | Focus |
|------|-------------|-------|
| **Sales/Leads Mode** | Businesses, SaaS companies | Lead generation, sales opportunities |
| **Insights Mode** | Researchers, Professors, Personal sites | Visitor engagement, content insights |

---

### Lead Stats Cards

#### Sales Mode

| Metric | Description | Calculation |
|--------|-------------|-------------|
| **Total Leads** | All scored conversations | `COUNT(*)` of LeadScore records |
| **Hot Leads** | High-intent visitors | `COUNT(*)` where priority='hot' |
| **Warm Leads** | Medium-intent visitors | `COUNT(*)` where priority='warm' |
| **Cold Leads** | Low-intent visitors | `COUNT(*)` where priority='cold' |
| **Hot Lead Rate** | % of leads that are hot | `(hot_leads / total_leads) * 100` |

#### Insights Mode (Reframed)

| Metric | Sales Equivalent | Description |
|--------|------------------|-------------|
| **Engaged Visitors** | Total Leads | All visitors who conversed |
| **Highly Interested** | Hot Leads | Very engaged visitors |
| **Moderately Engaged** | Warm Leads | Somewhat engaged visitors |
| **Casual Browsers** | Cold Leads | Brief interactions |
| **Engagement Rate** | Hot Lead Rate | % highly engaged |

---

### Lead Charts

#### Basic Tier (All Users)

##### 1. Leads Over Time (Stacked Area Chart)
- **What it shows**: Daily lead volume by priority
- **Data source**: `LeadScore` aggregated by date and priority
- **Calculation**: `COUNT(*)` grouped by `session_date`, `priority`
- **Colors**: Hot (red), Warm (amber), Cold (gray)

##### 2. Lead Distribution (Donut Chart)
- **What it shows**: Overall priority breakdown
- **Data source**: `LeadScore` summary
- **Calculation**: `COUNT(*)` grouped by `priority`

#### Premium Tier

##### 3. Geographic Distribution (Horizontal Bar Chart)
- **What it shows**: Leads by location
- **Data source**: `LeadScore.geo_location`
- **Calculation**: `COUNT(*)` grouped by `geo_location`
- **Top 10 locations displayed**

##### 4. Device Breakdown (Pie Chart)
- **What it shows**: Leads by device type
- **Data source**: `LeadScore.device_type`
- **Calculation**: `COUNT(*)` grouped by `device_type`

##### 5. Top Source Pages (Horizontal Bar Chart)
- **What it shows**: Which pages generate leads
- **Data source**: `LeadScore.source_url`
- **Calculation**: `COUNT(*)` grouped by `source_url`
- **Top 10 pages displayed**

##### 6. Chatbot Comparison (Stacked Bar Chart)
- **What it shows**: Lead performance across chatbots
- **Data source**: `LeadScore` grouped by chatbot
- **Calculation**: `COUNT(*)` by chatbot and priority

##### 7. Top Detected Intents (Horizontal Bar Chart)
- **What it shows**: What visitors are looking for
- **Data source**: `LeadScore.detected_intent`
- **Calculation**: `COUNT(*)` grouped by `detected_intent`

| Intent | Description |
|--------|-------------|
| `pricing_inquiry` | Asked about pricing/costs |
| `demo_request` | Requested a demo |
| `support` | Needed help with issues |
| `feature_inquiry` | Asked about features |
| `comparison` | Comparing with competitors |
| `partnership` | Partnership interest |
| `enterprise_inquiry` | Enterprise-level interest |
| `information` | General information seeking |

#### Enterprise Tier

##### 8. Score Distribution (Histogram)
- **What it shows**: Distribution of lead scores
- **Data source**: `LeadScore.total_score`
- **Buckets**: 0-20, 21-40, 41-60, 61-80, 81-100
- **User insight**: Understand overall lead quality distribution

##### 9. Lead Quality Trends (Composed Chart)
- **What it shows**: Score trends over time
- **Data elements**:
  - Bar: Average score per day
  - Line: Hot lead rate % per day
- **User insight**: Track if lead quality is improving or declining

---

### Lead Table

Displays individual lead records with the following columns:

| Column | Description |
|--------|-------------|
| **Name/Email** | Visitor identification (if provided) |
| **Score** | Total lead score (0-100) |
| **Priority** | Hot/Warm/Cold badge |
| **Intent** | Detected visitor intent |
| **Last Activity** | When conversation occurred |
| **Actions** | View details button |

**Features:**
- Pagination (page size varies by tier)
- Priority filtering
- Date range filtering

---

### Lead Detail Dialog

When clicking "View" on a lead, a dialog shows comprehensive information:

#### Basic Information
| Field | Description |
|-------|-------------|
| **Priority Badge** | Hot/Warm/Cold indicator |
| **Total Score** | Overall lead score |
| **Session Info** | Messages, duration, device, location |
| **Source URL** | Page where conversation started |
| **Feedback** | Positive/negative indicators |

#### Score Breakdown
| Component | Max Points | Description |
|-----------|------------|-------------|
| **Engagement Score** | 50 | Based on interaction depth |
| **Intent Score** | 50 | Based on detected buying signals |

Progress bars visualize each component.

#### Premium Features
| Section | Description |
|---------|-------------|
| **Key Questions** | List of questions the visitor asked |
| **Conversation Summary** | AI-generated summary |

#### Enterprise Features (LLM Insights)
| Section | Description |
|---------|-------------|
| **Intent Analysis** | Primary intent with confidence % |
| **Buying Signals** | Detected purchase indicators |
| **Objections** | Concerns raised by visitor |
| **Extracted Entities** | Company, title, team size, industry, budget, timeline, use case |
| **Competitor Mentions** | Any competitors mentioned |
| **Recommendations** | Follow-up action, talking points, content gaps |
| **AI Reasoning** | Explanation of scoring rationale |

---

## Visitor Insights Mode

Designed for individual users (researchers, professors, personal websites) who don't need sales-focused metrics.

### Engagement Stats

| Metric | Description | Calculation |
|--------|-------------|-------------|
| **Engaged Visitors** | Total conversations | Same as Total Leads |
| **Highly Interested** | Very engaged visitors | Same as Hot Leads |
| **Engagement Rate** | % highly engaged | `((highly + moderate) / total) * 100` |
| **Casual Browsers** | Brief interactions | Same as Cold Leads |

### Visitor Charts

Reframed versions of lead charts with visitor-focused terminology:

| Chart | Focus |
|-------|-------|
| **Visitor Activity** | Daily conversation volume |
| **Engagement Levels** | Highly Interested, Moderate, Casual |
| **What Visitors Ask About** | Topic/interest categories |
| **Audience Reach** | Geographic distribution |
| **Popular Content** | Pages driving conversations |

### Interest Mapping

Intents are reframed as topics for non-sales contexts:

| Intent | Topic Label |
|--------|-------------|
| `pricing` | Cost & Pricing |
| `demo` | Demonstrations |
| `support` | Help & Support |
| `comparison` | Comparisons |
| `features` | Features & Capabilities |
| `how_to` | How-To Guides |
| `information` | General Information |

### Common Questions

| Section | Description |
|---------|-------------|
| **Frequently Asked** | Most common visitor questions |
| **Content Gaps** | Questions the chatbot couldn't answer well |
| **Question Categories** | Topics visitors are interested in |

**User insight**: Use content gaps to improve your knowledge base.

---

## Lead Scoring System

### Score Components

Lead scores range from **0 to 100** and consist of two components:

#### Engagement Score (0-50 points)

| Factor | Points | Description |
|--------|--------|-------------|
| **Message Count** | 0-15 | More messages = higher engagement |
| **Session Duration** | 0-15 | Longer sessions = more interest |
| **Positive Feedback** | 0-10 | Thumbs up on responses |
| **Question Depth** | 0-10 | Detailed, specific questions |

**Calculation:**
```
engagement_score = min(50,
  message_count_score +
  duration_score +
  feedback_score +
  depth_score
)
```

#### Intent Score (0-50 points)

| Signal | Points | Keywords/Patterns |
|--------|--------|-------------------|
| **Pricing Interest** | 15 | "price", "cost", "pricing", "how much" |
| **Demo Request** | 20 | "demo", "trial", "try", "test" |
| **Contact Intent** | 15 | "contact", "call", "email", "schedule" |
| **Urgency** | 10 | "urgent", "asap", "immediately", "today" |
| **Company Mention** | 10 | Mentions company name or role |
| **Comparison** | 5 | "vs", "compare", "alternative" |

**Calculation:**
```
intent_score = min(50, sum(detected_signal_points))
```

### Priority Classification

| Priority | Score Range | Description |
|----------|-------------|-------------|
| **Hot** | 70-100 | High buying intent, ready to convert |
| **Warm** | 40-69 | Moderate interest, needs nurturing |
| **Cold** | 0-39 | Low intent, early research phase |

### AI/LLM Analysis

For Premium and Enterprise tiers, conversations are analyzed by an LLM (GPT-4o-mini) to extract:

#### Intent Analysis
```json
{
  "primary": "pricing_inquiry",
  "confidence": 85,
  "buying_signals": ["Asked for pricing", "Mentioned timeline"],
  "objections": ["Budget concerns"]
}
```

#### Entity Extraction
```json
{
  "company_name": "Acme Inc",
  "job_title": "CTO",
  "team_size": "50-100",
  "industry": "SaaS",
  "budget_signals": "Q1 budget approved",
  "timeline": "Next 30 days",
  "use_case": "Customer support automation"
}
```

#### Recommendations
```json
{
  "follow_up_action": "Schedule demo call within 24 hours",
  "talking_points": ["ROI calculator", "Implementation timeline"],
  "content_gaps": ["Security documentation"]
}
```

---

## Weekly Email Reports

Users receive automated weekly summaries of their leads/insights.

### Report Contents

| Section | Description |
|---------|-------------|
| **Header** | Report period and chatbot name |
| **Metrics Grid** | Total leads, hot/warm/cold counts, sessions |
| **Stats Row** | Avg messages, duration, feedback summary |
| **Top Leads** | Up to 5 top leads with summaries and buying signals |
| **Intent Breakdown** | Progress bars showing intent distribution |
| **Audience Reach** | Geographic distribution |
| **Common Questions** | Frequently asked questions |
| **CTA** | Link to dashboard |

### Report Configuration

Users can configure:
| Setting | Options |
|---------|---------|
| **Enabled** | On/Off |
| **Report Day** | Monday-Sunday |
| **Report Hour** | 0-23 |
| **Timezone** | User's timezone |
| **Include Cold Leads** | Yes/No |
| **Min Lead Score** | 0-100 threshold |

### Hot Lead Alerts

Immediate email notification when a hot lead is detected:
- Sent in real-time (if enabled)
- Contains lead details, questions, and summary
- Direct link to lead detail page

---

## Tier-Based Features

| Feature | Basic | Premium | Enterprise |
|---------|-------|---------|------------|
| **Analytics Retention** | 7 days | 30 days | 90 days |
| **Leads Per Page** | 10 | 50 | 100 |
| **Daily Activity Chart** | Yes | Yes | Yes |
| **Hourly/Weekly Charts** | No | Yes | Yes |
| **Geographic Analytics** | No | Yes | Yes |
| **Device Breakdown** | No | Yes | Yes |
| **Source Page Analysis** | No | Yes | Yes |
| **Intent Analysis** | No | Yes | Yes |
| **Chatbot Comparison** | No | Yes | Yes |
| **Top Queries Limit** | 5 | 20 | Unlimited |
| **Query Categories** | No | No | Yes |
| **Score Distribution** | No | No | Yes |
| **Quality Trends** | No | No | Yes |
| **LLM Insights** | No | Basic | Full |
| **Export Formats** | None | CSV | CSV, JSON |
| **Weekly Reports** | No | Yes | Yes |
| **Hot Lead Alerts** | No | No | Yes |

---

## API Reference

### Analytics Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/frontend/analytics/` | GET | Main analytics data |
| `/v1/frontend/analytics/queries/` | GET | Query analytics |
| `/v1/frontend/analytics/citations/` | GET | Citation analytics |
| `/v1/frontend/analytics/geo/` | GET | Geographic data |
| `/v1/frontend/analytics/feedback/` | GET | Feedback details |

### Leads Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/frontend/analytics/leads/` | GET | Leads dashboard |
| `/v1/frontend/analytics/leads/<id>/` | GET | Lead detail |
| `/v1/frontend/analytics/leads/export/` | GET | Export leads |

### Reports Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/frontend/analytics/reports/` | GET | Weekly reports list |
| `/v1/frontend/analytics/reports/<id>/` | GET | Report detail |
| `/v1/frontend/analytics/reports/generate/` | POST | Generate report |
| `/v1/frontend/analytics/reports/preferences/` | GET/PUT | Report settings |

### Common Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `days` | int | Number of days (limited by tier) |
| `site_id` | uuid | Filter by project/site |
| `chatbot_id` | uuid | Filter by chatbot |
| `priority` | string | Filter leads by priority |
| `page` | int | Pagination page number |
| `page_size` | int | Items per page |

---

## Data Models

### LeadScore Model

```python
class LeadScore:
    session           # OneToOne to ChatSession
    chatbot           # ForeignKey to Chatbot
    org_id            # UUID for multi-tenancy

    # Scores
    engagement_score  # 0-50
    intent_score      # 0-50
    total_score       # 0-100
    priority          # hot/warm/cold

    # Extracted Info
    detected_intent   # pricing, demo, support, etc.
    key_questions     # JSON list of questions
    conversation_summary  # AI-generated summary

    # Context
    source_url        # Page URL
    geo_location      # City, Country
    device_type       # desktop/mobile/tablet

    # Timing
    session_date      # Date of conversation
    session_duration_seconds
    message_count

    # Feedback
    had_positive_feedback
    had_negative_feedback

    # AI Analysis
    llm_insights      # JSON with full LLM analysis
```

### LLM Insights Structure

```json
{
  "analyzed_by_llm": true,
  "model_used": "gpt-4o-mini",
  "intent": {
    "primary": "pricing_inquiry",
    "confidence": 85,
    "buying_signals": ["Asked for pricing"],
    "objections": ["Budget concerns"]
  },
  "entities": {
    "company_name": "Acme Inc",
    "contact_email": "john@acme.com",
    "contact_name": "John Smith",
    "job_title": "CTO",
    "team_size": "50-100",
    "industry": "SaaS",
    "budget_signals": "Q1 budget",
    "timeline": "30 days",
    "use_case": "Customer support"
  },
  "sentiment": "positive",
  "urgency": "high",
  "engagement_quality": "high",
  "competitor_mentions": ["Intercom", "Zendesk"],
  "recommendations": {
    "follow_up_action": "Schedule demo",
    "talking_points": ["ROI", "Implementation"],
    "content_gaps": ["Security docs"]
  },
  "reasoning": "High intent signals with clear timeline and budget."
}
```

---

## Glossary

| Term | Definition |
|------|------------|
| **Lead** | A visitor who engaged with the chatbot and showed measurable intent |
| **Hot Lead** | High-intent visitor (score 70-100), likely to convert |
| **Warm Lead** | Medium-intent visitor (score 40-69), needs nurturing |
| **Cold Lead** | Low-intent visitor (score 0-39), early research phase |
| **Engagement Score** | Points based on interaction depth and quality |
| **Intent Score** | Points based on detected buying/action signals |
| **LLM Insights** | AI-extracted information from conversation analysis |
| **Buying Signals** | Indicators of purchase intent (pricing, demo, timeline) |
| **Content Gaps** | Topics the chatbot couldn't adequately address |
| **Session** | A single conversation between visitor and chatbot |
| **Citation** | Reference to a knowledge base page in a response |

---

*Last updated: January 2026*
*Version: 1.0*
