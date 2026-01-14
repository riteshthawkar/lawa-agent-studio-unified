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
                'name': 'Getting Started',
                'slug': 'getting-started',
                'description': 'Basic questions about setting up and using Webbotify',
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
                'answer': '''Webbotify can index various content types:

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
<script src="https://cdn.webbotify.com/widget.js"></script>
<script>
  WebbotifyWidget.init({
    apiKey: 'your-api-key',
    theme: 'auto'
  });
</script>
```

**Placement Tips:**
- Add the code just before the closing `</body>` tag
- The widget will automatically appear in the configured position
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
2. **API key**: Verify the API key is correct
3. **Console errors**: Check browser dev tools for errors
4. **Ad blockers**: Some may block the widget
5. **CORS issues**: Ensure your domain is allowed

**Common Fixes:**
```javascript
// Make sure init is called after the script loads
<script src="https://cdn.webbotify.com/widget.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', function() {
    WebbotifyWidget.init({ apiKey: 'your-key' });
  });
</script>
```

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
                'title': 'Getting Started with Webbotify',
                'slug': 'getting-started-guide',
                'article_type': 'getting_started',
                'icon': 'Rocket',
                'summary': 'Learn how to set up your first AI chatbot in minutes',
                'content': '''# Getting Started with Webbotify

Welcome to Webbotify! This guide will help you create your first AI-powered chatbot in just a few minutes.

## Step 1: Create Your Account

If you haven't already, sign up for a Webbotify account. You can start with our free trial to explore all features.

## Step 2: Create a Project

1. Click "New Project" from your dashboard
2. Enter your website URL
3. Give your project a name
4. Click "Create"

## Step 3: Index Your Website

Once your project is created, Webbotify will automatically begin indexing your website content. This process:

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
                'is_featured': True,
                'order': 2,
                'tags': ['customization', 'branding', 'design']
            },
            {
                'title': 'Understanding Website Indexing',
                'slug': 'understanding-indexing',
                'article_type': 'guide',
                'icon': 'Database',
                'summary': 'Learn how Webbotify indexes your website content for AI-powered responses',
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
                'order': 3,
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

  <!-- Webbotify Chat Widget -->
  <script src="https://cdn.webbotify.com/widget.js"></script>
  <script>
    WebbotifyWidget.init({
      apiKey: 'your-api-key-here'
    });
  </script>
</body>
</html>
```

## Configuration Options

```javascript
WebbotifyWidget.init({
  apiKey: 'your-api-key',      // Required
  theme: 'auto',               // 'light', 'dark', or 'auto'
  position: 'bottom-right',    // Widget position
  primaryColor: '#3b82f6',     // Override primary color
  welcomeMessage: 'Hello!'     // Override welcome message
});
```

## Platform-Specific Guides

### WordPress
Add the code to your theme's footer.php or use a plugin like "Insert Headers and Footers".

### Shopify
Add to your theme.liquid file before `</body>`.

### React/Next.js
```jsx
useEffect(() => {
  const script = document.createElement('script');
  script.src = 'https://cdn.webbotify.com/widget.js';
  script.onload = () => {
    window.WebbotifyWidget.init({ apiKey: 'your-key' });
  };
  document.body.appendChild(script);
}, []);
```

## Troubleshooting

If the widget doesn't appear:
1. Check browser console for errors
2. Verify the API key is correct
3. Ensure the script loads before init is called
4. Disable ad blockers temporarily to test
''',
                'is_featured': True,
                'order': 4,
                'tags': ['embed', 'installation', 'integration']
            },
        ]

        # Create or get a general category for articles
        general_cat, _ = FAQCategory.objects.get_or_create(
            slug='general',
            defaults={'name': 'General', 'order': 0}
        )

        for article_data in articles_data:
            article_data['category'] = general_cat
            article, created = HelpArticle.objects.update_or_create(
                slug=article_data['slug'],
                defaults=article_data
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} article: {article.title}')

        self.stdout.write(self.style.SUCCESS('Successfully seeded support data!'))
