"""
Management command to seed initial FAQ and Help Article data
"""
from django.core.management.base import BaseCommand
from apps.support.models import FAQ, FAQCategory, HelpArticle


class Command(BaseCommand):
    help = 'Seed initial FAQ and Help Article data'

    def handle(self, *args, **options):
        self.stdout.write('Seeding support data...')

        # Create FAQ Categories
        categories_data = [
            {
                'name': 'General Questions',
                'slug': 'general',
                'description': 'General information about Lawa Agent Studio',
                'icon': 'Question',
                'order': 0
            },
            {
                'name': 'Getting Started',
                'slug': 'getting-started',
                'description': 'Basic questions about setting up and using Lawa Agent Studio',
                'icon': 'Rocket',
                'order': 1
            },
            {
                'name': 'Chatbot Configuration',
                'slug': 'chatbot-configuration',
                'description': 'Questions about customizing your chatbot',
                'icon': 'Settings',
                'order': 2
            },
            {
                'name': 'Indexing & Content',
                'slug': 'indexing-content',
                'description': 'Questions about website indexing and content management',
                'icon': 'Database',
                'order': 3
            },
            {
                'name': 'Billing & Usage',
                'slug': 'billing-usage',
                'description': 'Questions about plans, billing, and usage limits',
                'icon': 'CreditCard',
                'order': 4
            },
            {
                'name': 'Troubleshooting',
                'slug': 'troubleshooting',
                'description': 'Common issues and how to resolve them',
                'icon': 'AlertTriangle',
                'order': 5
            },
        ]

        categories = {}
        for cat_data in categories_data:
            cat, created = FAQCategory.objects.update_or_create(
                slug=cat_data['slug'],
                defaults=cat_data
            )
            categories[cat_data['slug']] = cat
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} category: {cat.name}')

        # Create FAQs
        faqs_data = [
            # General Questions
            {
                'category': 'general',
                'question': 'What is Lawa Agent Studio?',
                'answer': '''Lawa Agent Studio is an AI-powered platform that enables you to create custom chatbots for your website in minutes. By indexing your website content, we create intelligent agents that can answer visitor questions accurately and instantly.''',
                'is_featured': True,
                'order': 1,
                'tags': ['about', 'platform', 'overview']
            },
            {
                'category': 'general',
                'question': 'Is my data secure?',
                'answer': '''Yes, security is our top priority. We use enterprise-grade encryption for all data in transit and at rest. We do not share your data with third parties, and your indexed content is only used to power your specific chatbot.''',
                'order': 2,
                'tags': ['security', 'privacy', 'data']
            },
             {
                'category': 'general',
                'question': 'Which languages do you support?',
                'answer': '''Lawa Agent Studio supports over 95 languages. The chatbot automatically detects the user's language and responds in the same language, utilizing the knowledge from your website regardless of its original language.''',
                'order': 3,
                'tags': ['languages', 'multilingual', 'support']
            },
            {
                'category': 'general',
                'question': 'Can I export my chat data?',
                'answer': '''Yes, you can export all conversation logs and lead data from your dashboard. We support CSV and JSON export formats for easy integration with your CRM or other tools.''',
                'order': 4,
                'tags': ['export', 'data', 'csv']
            },
            {
                'category': 'general',
                'question': 'Do I need to know how to code?',
                'answer': '''No coding skills are required! You can create, customize, and deploy your chatbot entirely through our user-friendly dashboard. Integration is as simple as copying and pasting a single line of code.''',
                'order': 5,
                'tags': ['no-code', 'easy', 'setup']
            },

            # Getting Started
            {
                'category': 'getting-started',
                'question': 'How do I create my first chatbot?',
                'answer': '''To create your first chatbot:

1. **Create a Project**: Go to the Projects page and click "New Project"
2. **Add Your Website**: Enter your website URL when prompted
3. **Wait for Indexing**: The system will crawl and index your website content
4. **Create Chatbot**: Once indexing is complete, click "Create Chatbot"
5. **Customize**: Configure the chatbot's appearance and behavior
6. **Embed**: Copy the embed code and add it to your website

Your chatbot will now be able to answer questions based on your website content!''',
                'is_featured': True,
                'order': 1,
                'tags': ['setup', 'quickstart', 'beginner']
            },
            {
                'category': 'getting-started',
                'question': 'How long does website indexing take?',
                'answer': '''Indexing time depends on your website size:

- **Small sites (< 50 pages)**: 1-5 minutes
- **Medium sites (50-200 pages)**: 5-15 minutes
- **Large sites (200+ pages)**: 15-60 minutes

Factors that affect indexing time:
- Number of pages to crawl
- Page load speeds
- JavaScript rendering requirements
- PDF processing (if enabled)

You can monitor indexing progress in real-time from your project dashboard.''',
                'is_featured': True,
                'order': 2,
                'tags': ['indexing', 'timing', 'performance']
            },
            {
                'category': 'getting-started',
                'question': 'What types of content can be indexed?',
                'answer': '''Lawa Agent Studio can index various content types:

**Supported Content:**
- HTML web pages
- PDF documents
- Text content from JavaScript-rendered pages
- Blog posts and articles
- Product descriptions
- Documentation pages

**Not Supported:**
- Password-protected pages
- Content behind login walls
- Video/audio transcripts (unless in text form)
- Images (alt text is captured)

For best results, ensure your content is publicly accessible and well-structured.''',
                'order': 3,
                'tags': ['content', 'supported', 'formats']
            },

            # Chatbot Configuration
            {
                'category': 'chatbot-configuration',
                'question': 'How do I customize my chatbot\'s appearance?',
                'answer': '''You can fully customize your chatbot's look and feel:

**Visual Customization:**
- **Primary Color**: Set your brand color for the chat bubble and header
- **Text Color**: Choose contrasting text colors
- **Position**: Place the widget in any corner of the screen
- **Size**: Adjust the chat window dimensions

**Behavioral Settings:**
- **Welcome Message**: Customize the greeting users see
- **Chatbot Tone**: Choose from professional, friendly, or casual
- **Response Length**: Control how detailed responses are
- **Placeholder Text**: Customize the input placeholder

Access these settings from your chatbot's Settings page.''',
                'is_featured': True,
                'order': 1,
                'tags': ['customization', 'appearance', 'branding']
            },
            {
                'category': 'chatbot-configuration',
                'question': 'How do I embed the chatbot on my website?',
                'answer': '''To embed your chatbot:

1. Go to your chatbot's Settings page
2. Find the "Embed Code" section
3. Copy the script tag
4. Paste it into your website's HTML

**Example embed code:**
```html
<script
  src="https://your-widget-url/widget.js"
  data-api-key="your-api-key"
  data-chatbot-name="My Assistant"
  data-theme="auto"
  data-position="bottom-right"
  async>
</script>
```

**Placement Tips:**
- Add the code just before the closing `</body>` tag
- The widget will automatically appear in the configured position
- All configuration is done via data attributes
- Test on a staging environment first''',
                'order': 2,
                'tags': ['embed', 'integration', 'website']
            },
            {
                'category': 'chatbot-configuration',
                'question': 'Can I use the chatbot on multiple websites?',
                'answer': '''Each chatbot is tied to a specific project (website):

**Single Domain:**
- One chatbot per project
- The chatbot answers questions based on that project's indexed content

**Multiple Websites:**
- Create separate projects for each website
- Each project can have its own chatbot
- Chatbots can be customized differently for each site

**Subdomains:**
- You can include subdomains during indexing
- One chatbot can serve content from multiple subdomains of the same domain''',
                'order': 3,
                'tags': ['multiple', 'domains', 'websites']
            },

            # Indexing & Content
            {
                'category': 'indexing-content',
                'question': 'How do I re-index my website after updates?',
                'answer': '''To update your indexed content:

1. Go to your Project dashboard
2. Navigate to the "Indexing" tab
3. Click "Re-index Website"
4. Wait for the indexing job to complete

**Best Practices:**
- Re-index after major content updates
- Schedule regular re-indexing for frequently updated sites
- Monitor the indexing job progress for any errors

The new content will be available to your chatbot once indexing completes.''',
                'is_featured': True,
                'order': 1,
                'tags': ['reindex', 'update', 'refresh']
            },
            {
                'category': 'indexing-content',
                'question': 'Why are some pages not being indexed?',
                'answer': '''Pages may not be indexed for several reasons:

**Common Causes:**
1. **robots.txt blocking**: Check if pages are disallowed
2. **No links to pages**: Orphan pages aren't discovered
3. **JavaScript-only content**: Some dynamic content may not render
4. **Password protection**: Login-required pages are skipped
5. **Max pages limit**: Your plan's page limit was reached

**Solutions:**
- Verify robots.txt allows crawling
- Ensure pages are linked from your main navigation
- Enable JavaScript rendering in indexing settings
- Upgrade your plan for more pages''',
                'order': 2,
                'tags': ['missing', 'pages', 'crawling', 'problems']
            },

            # Billing & Usage
            {
                'category': 'billing-usage',
                'question': 'What are the usage limits for my plan?',
                'answer': '''Usage limits vary by plan:

**Trial Plan:**
- 3 projects/sites
- 3 chatbots
- 100 pages per site
- 1,000 messages per month

**Starter Plan:**
- 10 projects/sites
- 10 chatbots
- 500 pages per site
- 10,000 messages per month

**Pro Plan:**
- Unlimited projects
- Unlimited chatbots
- 2,000 pages per site
- 100,000 messages per month

Check the Usage page in your dashboard for current consumption.''',
                'order': 1,
                'tags': ['limits', 'plans', 'pricing']
            },
            {
                'category': 'billing-usage',
                'question': 'How is message usage calculated?',
                'answer': '''Message usage is counted as follows:

**What counts as a message:**
- Each user question = 1 message
- Each chatbot response = 1 message
- Total per conversation = questions + responses

**What doesn't count:**
- Failed messages that weren't delivered
- System messages (welcome, error notices)
- Widget loads without interaction

**Monitoring Usage:**
- View real-time usage on the Usage page
- Set up alerts for usage thresholds
- Usage resets monthly on your billing date''',
                'order': 2,
                'tags': ['messages', 'counting', 'billing']
            },

            # Troubleshooting
            {
                'category': 'troubleshooting',
                'question': 'The chatbot isn\'t appearing on my website',
                'answer': '''If the chatbot widget isn't showing:

**Check These First:**
1. **Embed code placement**: Ensure it's before `</body>`
2. **API key**: Verify the data-api-key attribute is correct
3. **Console errors**: Check browser dev tools for errors
4. **Ad blockers**: Some may block the widget
5. **CORS issues**: Ensure your domain is allowed

**Common Fixes:**
```html
<!-- Make sure the script tag has all required attributes -->
<script
  src="https://your-widget-url/widget.js"
  data-api-key="your-api-key"
  data-chatbot-name="My Assistant"
  data-theme="auto"
  async>
</script>
```

**Verify:**
- The script src URL is correct and accessible
- The data-api-key matches your chatbot's API key
- No JavaScript errors in the console

If issues persist, contact support with your browser console output.''',
                'order': 1,
                'tags': ['widget', 'not showing', 'troubleshooting']
            },
            {
                'category': 'troubleshooting',
                'question': 'The chatbot gives incorrect or outdated answers',
                'answer': '''If responses are incorrect or outdated:

**Immediate Steps:**
1. **Re-index your website** to capture content updates
2. **Check indexed content** in the project dashboard
3. **Verify the source pages** contain correct information

**Improving Accuracy:**
- Ensure content is well-structured with clear headings
- Avoid duplicate content across pages
- Use descriptive text rather than images for key info
- Re-index after any content changes

**If Problems Persist:**
- Check if specific pages failed to index
- Review the chatbot's response settings
- Contact support with example queries and expected answers''',
                'order': 2,
                'tags': ['accuracy', 'wrong answers', 'outdated']
            },
            {
                'category': 'troubleshooting',
                'question': 'Indexing is stuck or taking too long',
                'answer': '''If indexing seems stuck:

**Wait Times by Site Size:**
- Small sites: Should complete within 5 minutes
- Large sites: May take up to 60 minutes
- Very large sites: Could take several hours

**If Genuinely Stuck:**
1. Check the indexing job status for errors
2. Cancel and restart the indexing job
3. Try indexing with a lower max pages limit first
4. Check if your website is responding slowly

**Common Causes:**
- Website rate limiting our crawler
- Very slow page load times
- Complex JavaScript requiring extra processing
- Network connectivity issues

Contact support if the problem persists after restarting.''',
                'order': 3,
                'tags': ['stuck', 'slow', 'indexing', 'timeout']
            },
        ]

        for faq_data in faqs_data:
            category_slug = faq_data.pop('category')
            category = categories.get(category_slug)
            faq_data['category'] = category

            faq, created = FAQ.objects.update_or_create(
                question=faq_data['question'],
                defaults=faq_data
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} FAQ: {faq.question[:50]}...')

        # Create Help Articles
        articles_data = [
            {
                'title': 'Getting Started with Lawa Agent Studio',
                'slug': 'getting-started-guide',
                'article_type': 'getting_started',
                'icon': 'Rocket',
                'summary': 'Learn how to set up your first AI chatbot in minutes',
                'content': '''# Getting Started with Lawa Agent Studio

Welcome to Lawa Agent Studio! This guide will help you create your first AI-powered chatbot in just a few minutes.

## Step 1: Create Your Account

If you haven't already, sign up for a Lawa Agent Studio account. You can start with our free trial to explore all features.

## Step 2: Create a Project

1. Click "New Project" from your dashboard
2. Enter your website URL
3. Give your project a name
4. Click "Create"

## Step 3: Index Your Website

Once your project is created, Lawa Agent Studio will automatically begin indexing your website content. This process:

- Crawls all accessible pages on your site
- Extracts and processes text content
- Creates searchable embeddings for AI responses

You can monitor progress from the project dashboard.

## Step 4: Create Your Chatbot

After indexing completes:

1. Navigate to your project
2. Click "Create Chatbot"
3. Customize appearance and behavior
4. Save your settings

## Step 5: Embed on Your Website

Copy the embed code from your chatbot settings and add it to your website. The widget will appear automatically!

## Next Steps

- [Customize your chatbot's appearance](/help-center/customizing-appearance)
- [Learn about advanced indexing options](/help-center/advanced-indexing)
- [Set up analytics tracking](/help-center/analytics-setup)
''',
                'category_slug': 'getting-started',
                'is_featured': True,
                'order': 1,
                'tags': ['beginner', 'setup', 'tutorial']
            },
            {
                'title': 'Customizing Your Chatbot Appearance',
                'slug': 'customizing-appearance',
                'article_type': 'guide',
                'icon': 'Palette',
                'summary': 'Make your chatbot match your brand with custom colors and styling',
                'content': '''# Customizing Your Chatbot Appearance

Make your chatbot feel like a natural part of your website with our customization options.

## Color Customization

### Primary Color
The primary color is used for:
- Chat bubble button
- Message bubbles from the chatbot
- Header background

Choose a color that matches your brand. Use hex codes like `#3b82f6`.

### Text Color
Ensure your text is readable against your primary color. We recommend:
- Light backgrounds: Use dark text (`#1a1a1a`)
- Dark backgrounds: Use light text (`#ffffff`)

## Position Settings

Place your chat widget where it works best for your site:
- **Bottom Right** (default): Most common placement
- **Bottom Left**: Good for RTL languages
- **Custom**: Set exact pixel positions

## Welcome Message

Customize the first message users see:

```
Hi! 👋 I'm here to help you find information about [Your Company].
Ask me anything!
```

Keep it friendly and set expectations about what the chatbot can help with.

## Response Settings

### Chatbot Tone
- **Professional**: Formal, business-appropriate responses
- **Friendly**: Warm and conversational
- **Casual**: Relaxed, informal style

### Response Length
- **Concise**: Short, direct answers
- **Balanced**: Moderate detail (recommended)
- **Detailed**: Comprehensive explanations
''',
                'category_slug': 'chatbot-configuration',
                'is_featured': True,
                'order': 1,
                'tags': ['customization', 'branding', 'design']
            },
            {
                'title': 'Understanding Website Indexing',
                'slug': 'understanding-indexing',
                'article_type': 'guide',
                'icon': 'Database',
                'summary': 'Learn how Lawa Agent Studio indexes your website content for AI-powered responses',
                'content': '''# Understanding Website Indexing

Website indexing is the process of crawling and processing your website content so your chatbot can answer questions accurately.

## How Indexing Works

### Phase 1: URL Discovery
Our crawler starts from your homepage and discovers pages by:
- Following internal links
- Respecting robots.txt rules
- Identifying sitemaps

### Phase 2: Content Extraction
For each discovered page:
- HTML content is parsed
- JavaScript is rendered (if enabled)
- Text is extracted and cleaned
- Metadata is captured

### Phase 3: AI Processing
Extracted content is:
- Split into semantic chunks
- Converted to vector embeddings
- Indexed for fast retrieval

## Indexing Settings

### Max Pages
Limit how many pages are indexed. Useful for:
- Large sites where you only need key pages
- Staying within plan limits
- Faster indexing times

### JavaScript Rendering
Enable for sites with:
- React, Vue, or Angular content
- Dynamically loaded content
- Single-page applications

### PDF Processing
When enabled, we'll extract and index content from PDF files linked on your site.

## Best Practices

1. **Structure your content well** - Use headings, lists, and clear paragraphs
2. **Update robots.txt** - Ensure important pages are crawlable
3. **Link important pages** - Make sure key content is discoverable
4. **Re-index regularly** - Keep content fresh after updates
''',
                'category_slug': 'indexing-content',
                'order': 1,
                'tags': ['indexing', 'crawling', 'content']
            },
            {
                'title': 'Embedding the Chat Widget',
                'slug': 'embedding-widget',
                'article_type': 'tutorial',
                'icon': 'Code',
                'summary': 'Step-by-step guide to adding the chatbot widget to your website',
                'content': '''# Embedding the Chat Widget

Add your AI chatbot to any website with our simple embed code.

## Basic Installation

### Step 1: Get Your Embed Code

1. Go to your chatbot's Settings page
2. Find the "Embed Code" section
3. Copy the code snippet

### Step 2: Add to Your Website

Paste the code just before the closing `</body>` tag:

```html
<!DOCTYPE html>
<html>
<head>
  <title>Your Website</title>
</head>
<body>
  <!-- Your website content -->

  <!-- Lawa Agent Studio Chat Widget -->
  <script
    src="https://your-widget-url/widget.js"
    data-api-key="your-api-key-here"
    data-chatbot-name="My Assistant"
    data-theme="auto"
    data-position="bottom-right"
    async>
  </script>
</body>
</html>
```

## Configuration Options

All configuration is done via `data-*` attributes on the script tag:

| Attribute | Description | Values |
|-----------|-------------|--------|
| `data-api-key` | Your chatbot API key (required) | String |
| `data-chatbot-name` | Display name for the chatbot | String |
| `data-theme` | Color theme | `light`, `dark`, `auto` |
| `data-position` | Widget position | `bottom-right`, `bottom-left` |
| `data-primary-color` | Brand color (hex) | e.g., `#3b82f6` |
| `data-text-color` | Text color (hex) | e.g., `#ffffff` |
| `data-greeting` | Welcome message | String |
| `data-placeholder` | Input placeholder | String |

## Platform-Specific Guides

### WordPress
Add the code to your theme's footer.php or use a plugin like "Insert Headers and Footers".

### Shopify
Add to your theme.liquid file before `</body>`.

### React/Next.js
```jsx
useEffect(() => {
  const script = document.createElement('script');
  script.src = 'https://your-widget-url/widget.js';
  script.setAttribute('data-api-key', 'your-api-key');
  script.setAttribute('data-chatbot-name', 'My Assistant');
  script.setAttribute('data-theme', 'auto');
  script.async = true;
  document.body.appendChild(script);
  
  return () => {
    document.body.removeChild(script);
  };
}, []);
```

## Troubleshooting

If the widget doesn't appear:
1. Check browser console for errors
2. Verify the `data-api-key` attribute is correct
3. Ensure the script src URL is accessible
4. Disable ad blockers temporarily to test
''',
                'category_slug': 'chatbot-configuration',
                'is_featured': True,
                'order': 2,
                'tags': ['embed', 'installation', 'integration']
            },
            # Indexing & Content Articles
            {
                'title': 'Re-indexing Your Website',
                'slug': 'reindexing-website',
                'article_type': 'guide',
                'icon': 'Database',
                'summary': 'How to update your chatbot knowledge when your website content changes',
                'content': '''# Re-indexing Your Website

Keep your chatbot up-to-date with the latest content from your website.

## When to Re-index

Re-index your website when:
- You've added new pages or content
- Existing content has been updated
- You've removed outdated pages
- Product information has changed

## How to Re-index

1. Navigate to your **Project Dashboard**
2. Go to the **Indexing** tab
3. Click **Re-index Website**
4. Monitor progress in the job list

## Indexing Options

| Option | Description |
|--------|-------------|
| Full Re-index | Crawls all pages from scratch |
| Incremental | Only updates changed pages (faster) |
| Specific URLs | Index only selected pages |

## Best Practices

- Schedule regular re-indexing for frequently updated sites
- Re-index after major content updates
- Check the indexing report for any failed pages
''',
                'category_slug': 'indexing-content',
                'order': 1,
                'tags': ['indexing', 'update', 'content']
            },
            {
                'title': 'Optimizing Content for Better Answers',
                'slug': 'optimizing-content',
                'article_type': 'guide',
                'icon': 'Database',
                'summary': 'Structure your website content for more accurate chatbot responses',
                'content': '''# Optimizing Content for Better Answers

Help your chatbot provide more accurate and helpful responses.

## Content Structure Tips

### Use Clear Headings
- Break content into logical sections
- Use H2 and H3 tags for sub-topics
- Make headings descriptive

### Write Concise Paragraphs
- Keep paragraphs focused on one topic
- Avoid long walls of text
- Use bullet points for lists

### Include FAQs on Your Site
- Create dedicated FAQ pages
- Use question-answer format
- Cover common customer queries

## What to Avoid

- **Duplicate content** - Confuses the AI
- **Images without alt text** - Text in images isn't indexed
- **Complex navigation** - Orphan pages may not be found
- **Login-protected content** - Cannot be crawled

## Testing Your Content

After indexing, test by asking your chatbot questions about:
- Recently added content
- Specific product details
- FAQ topics
''',
                'category_slug': 'indexing-content',
                'order': 2,
                'tags': ['content', 'optimization', 'accuracy']
            },
            # Billing & Usage Articles
            {
                'title': 'Understanding Your Usage Dashboard',
                'slug': 'usage-dashboard',
                'article_type': 'guide',
                'icon': 'CreditCard',
                'summary': 'Monitor your chatbot usage, message counts, and plan limits',
                'content': '''# Understanding Your Usage Dashboard

Track your resource consumption and stay within plan limits.

## Accessing the Dashboard

Navigate to **Settings > Usage** to view your current usage.

## Key Metrics

### Messages
- **Messages Used**: Total messages this billing period
- **Message Limit**: Maximum allowed by your plan
- **Usage %**: Percentage of limit consumed

### Projects & Chatbots
- **Active Projects**: Number of indexed websites
- **Active Chatbots**: Deployed chatbot widgets
- **Pages Indexed**: Total pages across all projects

## Usage Alerts

Set up alerts to notify you when:
- Usage reaches 80% of limit
- Usage reaches 90% of limit
- You're approaching page limits

## Upgrading Your Plan

If you're consistently hitting limits:
1. Go to **Settings > Billing**
2. Click **Upgrade Plan**
3. Choose a plan with higher limits
4. Confirm the upgrade

Changes take effect immediately.
''',
                'category_slug': 'billing-usage',
                'order': 1,
                'tags': ['usage', 'billing', 'limits']
            },
            {
                'title': 'Managing Your Subscription',
                'slug': 'managing-subscription',
                'article_type': 'guide',
                'icon': 'CreditCard',
                'summary': 'Upgrade, downgrade, or cancel your subscription',
                'content': '''# Managing Your Subscription

Control your plan and billing settings.

## Current Plan

View your current plan details at **Settings > Billing**.

## Upgrading

To upgrade your plan:
1. Go to **Settings > Billing**
2. Click **Change Plan**
3. Select a higher tier
4. Confirm payment

Upgrades are prorated - you only pay the difference.

## Downgrading

To downgrade:
1. Ensure usage is within new plan limits
2. Go to **Settings > Billing**
3. Select a lower tier
4. Downgrade takes effect at next billing cycle

## Cancellation

To cancel your subscription:
1. Go to **Settings > Billing**
2. Click **Cancel Subscription**
3. Your access continues until the billing period ends

## Payment Methods

Update your payment method:
1. Go to **Settings > Billing**
2. Click **Update Payment Method**
3. Enter new card details
''',
                'category_slug': 'billing-usage',
                'order': 2,
                'tags': ['subscription', 'billing', 'payment']
            },
            # Troubleshooting Articles
            {
                'title': 'Common Issues and Solutions',
                'slug': 'common-issues',
                'article_type': 'troubleshooting',
                'icon': 'AlertTriangle',
                'summary': 'Quick fixes for the most frequently encountered problems',
                'content': '''# Common Issues and Solutions

Quick solutions for frequently encountered problems.

## Widget Not Appearing

**Symptoms**: Chat bubble doesn't show on your website

**Solutions**:
1. Check embed code is before `</body>`
2. Verify `data-api-key` is correct
3. Check browser console for errors
4. Disable ad blockers temporarily

## Incorrect Answers

**Symptoms**: Chatbot gives wrong or outdated information

**Solutions**:
1. Re-index your website
2. Check if source pages have correct content
3. Verify pages were indexed (check index report)
4. Adjust response length settings

## Slow Responses

**Symptoms**: Chatbot takes too long to respond

**Solutions**:
1. Check your internet connection
2. Try refreshing the page
3. Check service status page
4. Contact support if issue persists

## Indexing Failures

**Symptoms**: Pages show as failed in index report

**Solutions**:
1. Verify pages are publicly accessible
2. Check robots.txt isn't blocking
3. Ensure pages load quickly
4. Try indexing specific URLs manually
''',
                'category_slug': 'troubleshooting',
                'is_featured': True,
                'order': 1,
                'tags': ['troubleshooting', 'issues', 'fixes']
            },
            {
                'title': 'Debugging Widget Issues',
                'slug': 'debugging-widget',
                'article_type': 'troubleshooting',
                'icon': 'AlertTriangle',
                'summary': 'Step-by-step guide to diagnose and fix widget problems',
                'content': '''# Debugging Widget Issues

Diagnose and resolve chat widget problems.

## Browser Developer Tools

Open DevTools (F12 or right-click > Inspect):

### Console Tab
Look for:
- JavaScript errors (red text)
- Network errors
- CORS warnings

### Network Tab
Check:
- Widget script loaded successfully (200 status)
- WebSocket connection established
- API requests returning data

## Common Error Messages

### "API key not found"
- Verify `data-api-key` attribute
- Check chatbot is active in dashboard
- Regenerate API key if needed

### "Connection failed"
- Check internet connectivity
- Verify API URLs are accessible
- Check firewall/VPN settings

### "CORS error"
- Ensure your domain is allowed
- Contact support if domain is correct

## Testing Checklist

✅ Script src URL is correct
✅ data-api-key matches dashboard
✅ No JavaScript errors in console
✅ Network requests are successful
✅ WebSocket connects properly
''',
                'category_slug': 'troubleshooting',
                'order': 2,
                'tags': ['debugging', 'widget', 'errors']
            },
        ]

        # Assign articles to their proper categories
        for article_data in articles_data:
            category_slug = article_data.pop('category_slug', 'general')
            category = categories.get(category_slug)
            if not category:
                # Fallback to general category
                category, _ = FAQCategory.objects.get_or_create(
                    slug='general',
                    defaults={'name': 'General', 'order': 0}
                )
            article_data['category'] = category
            article, created = HelpArticle.objects.update_or_create(
                slug=article_data['slug'],
                defaults=article_data
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} article: {article.title}')

        self.stdout.write(self.style.SUCCESS('Successfully seeded support data!'))

