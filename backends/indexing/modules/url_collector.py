"""
URL collection module for website crawling using Crawl4AI.
First phase: Collect all URLs from a website with page limit validation.
Enhanced with native Deep Crawling support and dynamic content handling.
"""

import asyncio
import logging
import time
from typing import Set, List, Dict, Any, Optional
from collections import deque

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import WebScrapingStrategy  # Use Pruning Strategy for better extraction
from robotexclusionrulesparser import RobotExclusionRulesParser
from urllib.parse import urlparse

from .config import CrawlerConfig, DynamicContentConfig
from .subdomain_discovery import SubdomainDiscovery, SubdomainConfig
from .dynamic_content_handler import DynamicContentHandler

logger = logging.getLogger(__name__)

# Add file handler for debugging
import os
log_file = os.path.join(os.path.dirname(__file__), '..', 'debug.log')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class URLCollector:
    """
    Collects all URLs from a website using Crawl4AI's native Deep Crawl.
    This is the first phase before processing individual URLs.
    Enhanced with dynamic content handling for JS/SPA/lazy loading support.
    """

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.start_url = config.start_url
        self.max_pages = max(1, config.max_pages)
        self.allowed_domains = set(config.allowed_domains) if config.allowed_domains else set()
        self.excluded_subdomains = set(config.excluded_subdomains) if config.excluded_subdomains else set()

        # Extract base domain from start URL for subdomain discovery
        parsed_start = urlparse(self.start_url)
        self.base_domain = parsed_start.netloc
        # Remove www prefix for subdomain matching
        if self.base_domain.startswith('www.'):
            self.base_domain = self.base_domain[4:]

        # Initialize subdomain discovery
        subdomain_config = SubdomainConfig(
            scrape_all_subdomains=config.scrape_all_subdomains,
            include_subdomains=config.include_subdomains or []
        )
        self.subdomain_discovery = SubdomainDiscovery(self.base_domain, subdomain_config)

        # Bug #13 fix: Initialize dynamic content handler for JS/SPA/lazy loading
        dynamic_config = DynamicContentConfig(
            infinite_scroll_enabled=config.infinite_scroll_enabled,
            infinite_scroll_max_scrolls=config.infinite_scroll_max_scrolls,
            shadow_dom_traversal=config.shadow_dom_traversal,
            lazy_load_images=config.lazy_load_images,
            scroll_stability_checks=config.scroll_stability_checks,
            scroll_wait_time=getattr(config, 'scroll_wait_time', 1.0),
            dynamic_content_wait=getattr(config, 'dynamic_content_wait', 5.0),
        )
        self.dynamic_handler = DynamicContentHandler(dynamic_config)
        self.dynamic_content_stats = {}

        # Results storage
        self.collected_results: List[Any] = []
        self.collected_urls: Set[str] = set()
        self.pdf_urls: Set[str] = set()  # Track PDF URLs separately

        logger.info(f"URLCollector initialized with Crawl4AI Deep Crawl for {self.start_url} (max: {self.max_pages} pages)")
        logger.info(f"Dynamic content handling: infinite_scroll={config.infinite_scroll_enabled}, "
                   f"shadow_dom={config.shadow_dom_traversal}, lazy_load={config.lazy_load_images}")
        if config.scrape_all_subdomains:
            logger.info(f"Subdomain discovery enabled for {self.base_domain}")

    async def collect_all_urls(self) -> Dict[str, Any]:
        """
        Collect all URLs from the website using Crawl4AI's BFSDeepCrawlStrategy.
        Enhanced with dynamic content handling for JS/SPA/lazy loading support.
        Returns a dictionary with collected URLs, content, and statistics.
        """
        try:
            logger.info(f"🚀 Starting Deep Crawl from {self.start_url}")
            logger.info(f"   Dynamic content: magic={self.config.magic}, "
                       f"infinite_scroll={self.config.infinite_scroll_enabled}, "
                       f"remove_overlays={self.config.remove_overlay_elements}")
            start_time = time.time()

            # Configure Deep Crawl Strategy with concurrency limit
            # Default to 5 concurrent pages to prevent overwhelming target servers
            max_concurrent_pages = int(os.getenv("CRAWLER_MAX_CONCURRENT_PAGES", "5"))
            deep_crawl_strategy = BFSDeepCrawlStrategy(
                max_depth=3,  # Default depth, can be configurable
                include_external=False,
                max_pages=self.max_pages,
            )

            # Bug #13 fix: Enhanced configuration for dynamic content
            # Build JavaScript for infinite scroll and lazy loading handling
            js_code = None
            if self.config.infinite_scroll_enabled or self.config.lazy_load_images:
                js_code = self._build_dynamic_content_js()

            # Configure Crawler Run with enhanced scraping and concurrency control
            run_config = CrawlerRunConfig(
                deep_crawl_strategy=deep_crawl_strategy,
                scraping_strategy=WebScrapingStrategy(),  # Use Pruning Strategy
                verbose=True,
                magic=self.config.magic,  # Enable JavaScript rendering
                # Link extraction enhancement - ensures navbar and all links are discovered
                scan_full_page=getattr(self.config, 'scan_full_page', True),
                delay_before_return_html=getattr(self.config, 'delay_before_return_html', 2.0),
                wait_for=self.config.wait_for if self.config.wait_for else None,
                css_selector=self.config.css_selector if self.config.css_selector else None,
                remove_overlay_elements=self.config.remove_overlay_elements,
                # Bug #13 fix: Add JavaScript execution for dynamic content
                js_code=js_code,
                # Increase timeout for dynamic content loading
                page_timeout=getattr(self.config, 'dynamic_content_wait', 5.0) * 1000 + 30000,
                # Concurrency control - limit parallel page fetches
                semaphore_count=max_concurrent_pages,
            )

            # Production Enhancement: Configure browser with stealth mode for better compatibility
            # This helps with JS-heavy sites, SPAs, and sites that block bots
            browser_config = BrowserConfig(
                headless=True,
                browser_type="chromium",
                # Stealth mode: use realistic user agent to avoid bot detection
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                # Optimal viewport for content extraction
                viewport_width=1920,
                viewport_height=1080,
                # Enable JavaScript for SPAs and dynamic content
                java_script_enabled=True,
                # Verbose for debugging
                verbose=True,
            )
            
            logger.info("Browser configured with stealth mode for versatile crawling")

            async with AsyncWebCrawler(config=browser_config) as crawler:

                # Run the deep crawl with timeout protection
                # Production Fix #3: Prevent indefinite hangs on stuck crawls
                # Timeout: max_pages * 30s, capped at 30 minutes
                crawl_timeout = min(self.max_pages * 30, 1800)  # Max 30 minutes
                logger.info(f"   Crawl timeout: {crawl_timeout} seconds")
                
                try:
                    # Note: arun() with deep_crawl_strategy returns a list of CrawlResult objects
                    results = await asyncio.wait_for(
                        crawler.arun(
                            url=self.start_url,
                            config=run_config
                        ),
                        timeout=crawl_timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Deep crawl timed out after {crawl_timeout} seconds")
                    return {
                        "status": "failed",
                        "error": f"Crawl timed out after {crawl_timeout} seconds",
                        "urls": list(self.collected_urls),
                        "pdf_urls": list(self.pdf_urls),
                        "results": [],
                        "stats": {
                            "start_url": self.start_url,
                            "max_pages": self.max_pages,
                            "urls_collected": len(self.collected_urls),
                            "duration": time.time() - start_time,
                            "timeout": True
                        },
                        "message": "Crawl was terminated due to timeout"
                    }

                # Process results
                self.collected_results = results
                self.collected_urls = set()
                self.pdf_urls = set()

                for r in results:
                    if r.success:
                        url = r.url
                        self.collected_urls.add(url)

                        # Check if this is a PDF URL
                        if self._is_pdf_url(url):
                            self.pdf_urls.add(url)

                        # Discover subdomains from collected URLs
                        self.subdomain_discovery.discover_from_url(url)

                duration = time.time() - start_time

                # Get subdomain discovery stats
                subdomain_stats = self.subdomain_discovery.get_stats()

                logger.info(f"✅ Deep Crawl completed in {duration:.2f}s")
                logger.info(f"   - Pages found: {len(results)}")
                logger.info(f"   - Successful: {len(self.collected_urls)}")
                logger.info(f"   - PDF URLs: {len(self.pdf_urls)}")
                if subdomain_stats["subdomains_discovered"] > 0:
                    logger.info(f"   - Subdomains discovered: {subdomain_stats['discovered_subdomains']}")

                # Get dynamic content handler stats
                dynamic_stats = self.dynamic_handler.get_stats()

                # Prepare return data
                # We return the raw results too so Phase 2 can use the pre-fetched content
                return {
                    "status": "completed",
                    "urls": list(self.collected_urls),
                    "pdf_urls": list(self.pdf_urls),
                    "results": results,  # Pass full results to next phase
                    "stats": {
                        "start_url": self.start_url,
                        "max_pages": self.max_pages,
                        "urls_collected": len(self.collected_urls),
                        "pdf_urls_found": len(self.pdf_urls),
                        "pages_visited": len(results),
                        "duration": duration,
                        "subdomain_discovery": subdomain_stats,
                        # Bug #13 fix: Include dynamic content handling stats
                        "dynamic_content": {
                            "infinite_scroll_enabled": self.config.infinite_scroll_enabled,
                            "shadow_dom_enabled": self.config.shadow_dom_traversal,
                            "lazy_load_enabled": self.config.lazy_load_images,
                            "spa_pages_detected": dynamic_stats.get("spa_pages_detected", 0),
                            "infinite_scroll_detected": dynamic_stats.get("infinite_scroll_detected", 0),
                            "shadow_dom_elements_found": dynamic_stats.get("shadow_dom_elements_found", 0),
                            "lazy_images_loaded": dynamic_stats.get("lazy_images_loaded", 0),
                        }
                    },
                    "discovered_subdomains": self.subdomain_discovery.get_discovered_subdomains(),
                    "allowed_domains": self.subdomain_discovery.build_allowed_domains(),
                    "message": f"Successfully collected {len(self.collected_urls)} URLs via Deep Crawl"
                }

        except Exception as e:
            logger.error(f"❌ Error in Deep Crawl: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "urls": [],
                "pdf_urls": [],
                "results": [],
                "stats": {},
                "discovered_subdomains": [],
                "allowed_domains": []
            }

    def _is_pdf_url(self, url: str, content_type: str = None) -> bool:
        """
        Check if a URL points to a PDF file.
        Uses URL extension heuristics and optional Content-Type header.

        Args:
            url: The URL to check
            content_type: Optional Content-Type header value

        Returns:
            True if URL appears to be a PDF
        """
        # Check URL extension (remove query params and fragments)
        url_lower = url.lower().split('?')[0].split('#')[0]
        if url_lower.endswith('.pdf'):
            return True

        # Check Content-Type if provided
        if content_type and 'application/pdf' in content_type.lower():
            return True

        # Check for common PDF download patterns in URL
        pdf_patterns = [
            '/download/pdf/',
            '/pdf/download/',
            '/export/pdf',
            '/generate-pdf',
            '/get-pdf',
            'format=pdf',
            'type=pdf',
            'output=pdf',
        ]
        url_lower_full = url.lower()
        for pattern in pdf_patterns:
            if pattern in url_lower_full:
                return True

        return False

    def _build_dynamic_content_js(self) -> str:
        """
        Build JavaScript code for handling dynamic content during crawling.
        Bug #13 fix: This enables proper handling of infinite scroll, lazy loading, and SPAs.
        """
        max_scrolls = self.config.infinite_scroll_max_scrolls
        scroll_wait = int(getattr(self.config, 'scroll_wait_time', 1.0) * 1000)
        stability_checks = self.config.scroll_stability_checks

        js_code = f"""
        (async () => {{
            // Dynamic content handler - executed on each page
            const maxScrolls = {max_scrolls};
            const scrollWait = {scroll_wait};
            const stabilityChecks = {stability_checks};

            // 1. Handle lazy loading images first
            const handleLazyImages = async () => {{
                const lazySelectors = [
                    'img[loading="lazy"]',
                    'img[data-src]',
                    'img[data-lazy]',
                    'img.lazy',
                    'img.lazyload',
                    'img[data-srcset]'
                ];

                const lazyImages = [];
                for (const selector of lazySelectors) {{
                    document.querySelectorAll(selector).forEach(img => {{
                        if (!lazyImages.includes(img)) lazyImages.push(img);
                    }});
                }}

                for (const img of lazyImages) {{
                    try {{
                        img.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                        if (img.dataset.src && !img.src) {{
                            img.src = img.dataset.src;
                        }}
                        await new Promise(r => setTimeout(r, 50));
                    }} catch (e) {{ }}
                }}
            }};

            // 2. Handle infinite scroll
            const handleInfiniteScroll = async () => {{
                let lastHeight = 0;
                let stableCount = 0;

                for (let i = 0; i < maxScrolls; i++) {{
                    const currentHeight = document.body.scrollHeight;

                    if (currentHeight === lastHeight) {{
                        stableCount++;
                        if (stableCount >= stabilityChecks) break;
                    }} else {{
                        stableCount = 0;
                        lastHeight = currentHeight;
                    }}

                    window.scrollTo(0, document.body.scrollHeight);
                    await new Promise(r => setTimeout(r, scrollWait));
                }}

                window.scrollTo(0, 0);
            }};

            // 3. Expand collapsed content (accordions, details)
            const expandCollapsedContent = async () => {{
                const expandableSelectors = [
                    'details:not([open])',
                    '[aria-expanded="false"]',
                    '.collapsed:not(.expanded)',
                    '.accordion-toggle:not(.active)',
                    '.expand-button',
                    '.show-more:not(.clicked)'
                ];

                for (const selector of expandableSelectors) {{
                    const elements = document.querySelectorAll(selector);
                    for (const el of elements) {{
                        try {{
                            if (el.tagName === 'DETAILS') {{
                                el.setAttribute('open', '');
                            }} else {{
                                el.click();
                            }}
                            await new Promise(r => setTimeout(r, 100));
                        }} catch (e) {{ }}
                    }}
                }}
            }};

            // 4. Click "Load More" buttons
            const handleLoadMoreButtons = async () => {{
                const loadMoreSelectors = [
                    'button[class*="load-more"]',
                    'button[class*="show-more"]',
                    'a[class*="load-more"]',
                    '.load-more',
                    '.show-more',
                    '#load-more'
                ];

                for (let i = 0; i < 3; i++) {{  // Try up to 3 times
                    for (const selector of loadMoreSelectors) {{
                        const btn = document.querySelector(selector);
                        if (btn && btn.offsetParent !== null) {{
                            try {{
                                btn.click();
                                await new Promise(r => setTimeout(r, 1000));
                            }} catch (e) {{ }}
                        }}
                    }}
                }}
            }};

            // Execute all handlers
            try {{
                await handleLazyImages();
                await handleInfiniteScroll();
                await expandCollapsedContent();
                await handleLoadMoreButtons();
                await handleLazyImages();  // Re-trigger after scroll
            }} catch (e) {{
                console.error('Dynamic content handler error:', e);
            }}
        }})();
        """

        return js_code

    def get_collected_urls(self) -> List[str]:
        """Get the list of collected URLs."""
        return list(self.collected_urls)

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        return {
            "urls_collected": len(self.collected_urls),
            "pages_visited": len(self.collected_results)
        }
