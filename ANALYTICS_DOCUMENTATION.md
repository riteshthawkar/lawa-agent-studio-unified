# Analytics &amp; Leads Dashboard Documentation

This document explains every component, chart, and metric on the **Leads Dashboard** and **Analytics Page**, detailing what each computes, its inputs, processing logic, outputs, and user value.

---

## Part I: Leads Dashboard

The Leads Dashboard helps organizations identify and prioritize high-intent website visitors who engaged with their chatbot.

### 1. Stats Cards (`stats-cards.jsx`)

| Metric | Input | Processing | Output | User Value |
|--------|-------|------------|--------|------------|
| **Total Leads** | `summary.total_leads` | Direct count from API | Number of unique visitors with meaningful engagement | Understand overall lead volume |
| **Hot Leads** | `summary.hot_leads` | Count of leads with score 70-100 | Count of high-intent visitors | Prioritize immediate follow-up |
| **Warm Leads** | `summary.warm_leads`, `summary.cold_leads` | Count of leads with score 40-69 (warm) and 0-39 (cold) | Both counts displayed | Identify nurturing opportunities |
| **Hot Lead Rate** | `hot_leads / total_leads * 100` | Percentage calculation | Percentage value | Measure chatbot qualification effectiveness |

#### Lead Scoring System
- **Hot (70-100)**: Showed buying signals like pricing inquiries, demo requests, urgency expressions
- **Warm (40-69)**: Asked relevant questions but no strong purchase intent
- **Cold (0-39)**: Early-stage information gathering

---

### 2. Leads Over Time Chart

| Field | Description |
|-------|-------------|
| **Input** | `leads_by_day[]` - Array with date, total, hot, warm, cold counts |
| **Processing** | Maps dates to formatted labels, stacks areas by priority |
| **Visualization** | Stacked Area Chart (Recharts) |
| **Output** | Daily trend showing lead acquisition by priority |
| **User Value** | Identify traffic patterns, measure campaign effectiveness, spot anomalies |

---

### 3. Lead Distribution (Priority Pie Chart)

| Field | Description |
|-------|-------------|
| **Input** | `hot_leads`, `warm_leads`, `cold_leads` counts |
| **Processing** | Creates pie segments with priority colors (Red=Hot, Orange=Warm, Blue=Cold) |
| **Visualization** | Donut Chart |
| **Output** | Visual breakdown of lead quality distribution |
| **User Value** | Quickly assess lead pool health at a glance |

---

### 4. Geographic Distribution (Premium)

| Field | Description |
|-------|-------------|
| **Input** | `geo_distribution{}` - Object with country names as keys, counts as values |
| **Processing** | Sorts by count descending, takes top 8 countries |
| **Visualization** | Horizontal Bar Chart |
| **Output** | Ranked list of countries generating leads |
| **User Value** | Identify target markets, plan regional campaigns, optimize chatbot language |

---

### 5. Device Breakdown (Premium)

| Field | Description |
|-------|-------------|
| **Input** | `device_breakdown{}` - Object with device types (desktop/mobile/tablet) as keys |
| **Processing** | Maps devices to colors, filters out zero-count entries |
| **Visualization** | Donut Chart |
| **Output** | Distribution of leads by device type |
| **User Value** | Ensure chatbot is optimized for primary audience devices |

---

### 6. Top Source Pages (Premium)

| Field | Description |
|-------|-------------|
| **Input** | `source_pages[]` - Array with URL, lead_count, hot_count |
| **Processing** | Extracts pathname from URLs, takes top 6 pages |
| **Visualization** | Horizontal Bar Chart |
| **Output** | Which website pages generate most leads |
| **User Value** | Identify high-converting content, optimize underperforming pages |

---

### 7. Chatbot Comparison (Premium)

| Field | Description |
|-------|-------------|
| **Input** | `chatbot_comparison[]` - Array with name, total_leads, hot_leads, warm_leads, avg_score |
| **Processing** | Maps chatbot data to stacked bar format |
| **Visualization** | Stacked Bar Chart |
| **Output** | Compare lead generation across different chatbots |
| **User Value** | Identify which chatbot configurations perform best |

---

### 8. Top Detected Intents (Premium)

| Field | Description |
|-------|-------------|
| **Input** | `top_intents[]` - Array with intent name and count |
| **Processing** | AI analyzes conversations to detect visitor intent, takes top 6 |
| **Visualization** | Horizontal Bar Chart |
| **Output** | Most common visitor intentions (pricing, demo, support, etc.) |
| **User Value** | High-value intents (pricing, demo) indicate hot leads |

---

### 9. Score Distribution (Enterprise)

| Field | Description |
|-------|-------------|
| **Input** | `score_distribution[]` - Array with min, max, count for score ranges |
| **Processing** | Buckets leads into score ranges (0-10, 11-20, etc.) |
| **Visualization** | Histogram (Bar Chart) |
| **Output** | Distribution of leads across the 0-100 score spectrum |
| **User Value** | Healthy distribution shows leads spread with meaningful portion in 70-100 range |

---

### 10. Quality Trends (Enterprise)

| Field | Description |
|-------|-------------|
| **Input** | `quality_trends[]` - Array with date, avg_score, hot_rate |
| **Processing** | Maps to composite chart showing both avg score and hot rate over time |
| **Visualization** | Composed Chart (Area + Line) |
| **Output** | How lead quality changes over time |
| **User Value** | Track improvement in lead quality, measure impact of chatbot optimizations |

---

### 11. Leads Table (`leads-table.jsx`)

| Field | Description |
|-------|-------------|
| **Input** | Full leads array with all lead details |
| **Columns** | Priority, Intent, Score, Location, Device, Source Page, Date, Actions |
| **Processing** | Sortable, filterable, paginated table |
| **Features** | Export to CSV, view lead details, filter by priority |
| **User Value** | Drill down into individual leads for sales follow-up |

---

### 12. Common Questions (`common-questions.jsx`)

| Field | Description |
|-------|-------------|
| **Input** | Aggregated questions from lead conversations |
| **Processing** | Clusters similar questions, ranks by frequency |
| **Output** | List of most frequently asked questions by leads |
| **User Value** | Identify common concerns, improve chatbot responses, create FAQ content |

---

## Part II: Analytics Page

The Analytics Page provides comprehensive insights into chatbot performance, user engagement, and content effectiveness.

### 1. Stats Cards (`stats-cards.jsx`)

| Metric | Input | Processing | Output | User Value |
|--------|-------|------------|--------|------------|
| **Total Sessions** | `stats.total_sessions` | Direct count | Total chatbot conversations | Measure overall usage |
| **Messages** | `stats.total_messages` | Direct count | Total chat messages exchanged | Understand engagement depth |
| **Unique Users** | `stats.unique_users` | Deduplicated visitor count | Distinct visitors | Measure reach |
| **Avg Rating** | `stats.avg_rating` | Average of user feedback ratings | Star rating (1-5) | User satisfaction metric |
| **Positive Rate** | `stats.positive_feedback / (positive + negative) * 100` | Percentage calculation | Satisfaction percentage | Quick health indicator |
| **Avg Session Length** | `stats.avg_session_duration` | Average time per session | Duration in seconds/minutes | Engagement depth |

---

### 2. Query Analytics (`query-analytics.jsx`)

#### Stats Cards
| Stat | Description |
|------|-------------|
| **Total Queries** | Count of all questions asked |
| **Unique Queries** | Distinct questions (deduplicated) |
| **Repeat Rate** | Percentage of queries asked multiple times |
| **Avg Query Length** | Average character length of questions |

#### Daily Query Volume
| Field | Description |
|-------|-------------|
| **Input** | `query_volume[]` - Array with date and queries count |
| **Visualization** | Bar Chart |
| **User Value** | Identify usage patterns, peak days, trend changes |

#### Top Queries
| Field | Description |
|-------|-------------|
| **Input** | `top_queries[]` - Array with query text and count |
| **Processing** | Ranked by frequency, limited by tier |
| **Output** | Most frequently asked questions |
| **User Value** | Understand what users care about most, improve content |

#### Query Categories (Premium/Enterprise)
| Field | Description |
|-------|-------------|
| **Input** | `query_categories[]` - AI-categorized queries |
| **Categories** | How-To, What-Is, Pricing, Support, Features, Other |
| **User Value** | Understand intent distribution, focus content efforts |

#### Unanswered Questions
| Field | Description |
|-------|-------------|
| **Input** | Queries with negative feedback (thumbs down) |
| **User Value** | Identify knowledge gaps, improve knowledge base |

---

### 3. Geographic Analytics (`geo-analytics.jsx`)

#### Stats Cards
| Stat | Description |
|------|-------------|
| **Total Sessions** | Total chatbot sessions with geo data |
| **Countries** | Number of distinct countries |
| **Top Country** | Country with most sessions |
| **Geo Coverage** | Percentage of sessions with resolved geo data |

#### Sessions by Country
| Field | Description |
|-------|-------------|
| **Input** | `countries[]` - Array with country_name, country_code, sessions, percentage |
| **Visualization** | Ranked list with progress bars and country flags |
| **User Value** | Understand global audience, localization priorities |

---

### 4. Citation Analytics (`citation-analytics.jsx`)

| Field | Description |
|-------|-------------|
| **Input** | Which knowledge base pages are cited in chatbot responses |
| **Processing** | Counts citations per source document |
| **Output** | Ranked list of most-used knowledge sources |
| **User Value** | Identify high-value content, find underutilized documents |

---

### 5. Feedback Details (`feedback-details.jsx`)

| Field | Description |
|-------|-------------|
| **Input** | User thumbs up/down feedback on responses |
| **Metrics** | Positive count, Negative count, Feedback rate |
| **Breakdown** | Recent feedback items with query context |
| **User Value** | Identify problematic responses, improve chatbot accuracy |

---

### 6. Starter Analytics (`starter-analytics.jsx`)

| Field | Description |
|-------|-------------|
| **Input** | Click counts on conversation starter buttons |
| **Processing** | Ranks starters by click frequency |
| **Output** | Most popular conversation starters |
| **User Value** | Optimize starter buttons, understand user intent |

---

### 7. Enhanced Analytics (`enhanced-analytics.jsx`)

Advanced analytics section combining multiple insights:

| Component | Description |
|-----------|-------------|
| **Traffic Insights** | Session volume over time, peak hours |
| **Engagement Metrics** | Messages per session, session duration |
| **Performance Trends** | Response quality over time |

---

### 8. Indexing Health (`indexing-health.jsx`)

| Field | Description |
|-------|-------------|
| **Input** | Knowledge base indexing status |
| **Metrics** | Total pages indexed, last indexing time, errors |
| **User Value** | Ensure knowledge base is up-to-date |

---

## Data Flow Summary

```
User Interacts with Chatbot
         ↓
Session Created (captures device, geo, referrer)
         ↓
Messages Exchanged (recorded with timestamps)
         ↓
Feedback Collected (thumbs up/down)
         ↓
AI Analysis (intent detection, scoring, summarization)
         ↓
Lead Record Created (if qualifying engagement)
         ↓
Analytics Aggregated (hourly/daily rollups)
         ↓
Dashboard Visualizations
```

---

## Tier Feature Availability

| Feature | Basic | Premium | Enterprise |
|---------|-------|---------|------------|
| Total Leads / Stats | ✅ | ✅ | ✅ |
| Leads Over Time | ✅ | ✅ | ✅ |
| Priority Distribution | ✅ | ✅ | ✅ |
| Geographic Distribution | ❌ | ✅ | ✅ |
| Device Breakdown | ❌ | ✅ | ✅ |
| Source Pages | ❌ | ✅ | ✅ |
| Chatbot Comparison | ❌ | ✅ | ✅ |
| Intent Analysis | ❌ | ✅ | ✅ |
| Score Distribution | ❌ | ❌ | ✅ |
| Quality Trends | ❌ | ❌ | ✅ |
| Query Categories | ❌ | ❌ | ✅ |
| Full Query List | Limited | Expanded | Unlimited |
