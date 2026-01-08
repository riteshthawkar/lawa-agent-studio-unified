"""
Web crawler module for scraping websites and downloading files.
Handles HTML pages, PDFs, and other document types with advanced features.
"""

import os
import asyncio
import logging
import hashlib
import random
import tempfile
from pathlib import Path
from typing import Set, Dict, Optional, List, Callable, Awaitable
from urllib.parse import urljoin, urlparse
from collections import deque, defaultdict

import aiohttp
from aiolimiter import AsyncLimiter
from playwright.async_api import (
    async_playwright, Page, Browser, BrowserContext,
    TimeoutError as PlaywrightTimeoutError, Response, Route
)
from robotexclusionrulesparser import RobotExclusionRulesParser
from tenacity import retry, RetryError
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename

from .config import CrawlerConfig
from .dynamic_content_handler import DynamicContentHandler, DynamicContentConfig

logger = logging.getLogger(__name__)


class WebCrawler:
    """Advanced web crawler with support for dynamic content and file downloads."""

    def __init__(self, config: CrawlerConfig, dynamic_config: DynamicContentConfig = None):
        self.config = config
        self.start_url = config.start_url
        self.start_domain = urlparse(self.start_url).netloc if self.start_url else ''

        # State management
        self.visited: Set[str] = set()
        self.to_visit: deque = deque()
        self.url_mapping: Dict[str, str] = {}
        self.stats = defaultdict(int)

        # Domain control
        self.allowed_domains = set(config.allowed_domains)
        if self.start_domain:
            self.allowed_domains.add(self.start_domain)
        self.excluded_subdomains = set(config.excluded_subdomains)

        # Concurrency control
        self.fetch_semaphore = asyncio.Semaphore(config.fetch_concurrency)
        self.download_semaphore = asyncio.Semaphore(config.download_concurrency)
        self.host_limiters: Dict[str, AsyncLimiter] = {}

        # Robots.txt handling
        self.robot_parsers: Dict[str, RobotExclusionRulesParser] = {}
        self._robots_fetch_tasks: Dict[str, asyncio.Task] = {}

        # Resource management
        self.p = None
        self.browser = None
        self.context = None
        self.http_session = None
        self.tasks = set()
        self._autosave_task: Optional[asyncio.Task] = None

        # Callbacks for streaming mode
        self.on_page_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.on_file_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

        # Initialize dynamic content handler
        # Use config values to build DynamicContentConfig if not provided
        if dynamic_config is None:
            dynamic_config = DynamicContentConfig(
                infinite_scroll_enabled=config.infinite_scroll_enabled,
                infinite_scroll_max_scrolls=config.infinite_scroll_max_scrolls,
                shadow_dom_traversal=config.shadow_dom_traversal,
                lazy_load_images=config.lazy_load_images,
                scroll_stability_checks=config.scroll_stability_checks
            )
        self.dynamic_handler = DynamicContentHandler(dynamic_config)
        self.dynamic_config = dynamic_config

        # Stealth configuration
        self.stealth_script = None
        if config.stealth:
            self.stealth_script = """
            () => {
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = {"runtime": {}};
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            }
            """

    async def _initialize_resources(self):
        """Initialize Playwright, browser, and HTTP session."""
        if self.p and self.browser and self.context and self.http_session:
            return

        self.p = await async_playwright().start()
        self.browser = await self.p.chromium.launch(headless=self.config.headless)
        self.context = await self.browser.new_context(
            user_agent=random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
            ]),
            viewport={"width": 1920, "height": 1080},
            locale='en-US'
        )
        
        # Block unnecessary resources
        await self.context.route("**/*", self._block_resources_handler)
        
        # HTTP session for downloads
        connector = aiohttp.TCPConnector(limit=self.config.fetch_concurrency)
        self.http_session = aiohttp.ClientSession(connector=connector)

    async def _block_resources_handler(self, route: Route):
        """Block unnecessary resources to speed up crawling."""
        resource_types_to_block = ["image", "stylesheet", "font", "media"]
        if route.request.resource_type in resource_types_to_block:
            await route.abort()
        else:
            await route.continue_()

    async def _fetch_robots_txt(self, domain: str):
        """Fetch and parse robots.txt for a domain."""
        url = urljoin(f"https://{domain}", "/robots.txt")
        try:
            async with self.http_session.get(url, timeout=self.config.timeout) as response:
                if response.status == 200:
                    text = await response.text()
                    parser = RobotExclusionRulesParser()
                    parser.parse(text)
                    self.robot_parsers[domain] = parser
                else:
                    self.robot_parsers[domain] = None
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt for {domain}: {e}")
            self.robot_parsers[domain] = None

    async def ensure_robots_rules(self, hostname: str):
        """Ensure robots.txt is fetched for a hostname."""
        if hostname in self.robot_parsers or not hostname:
            return
        if hostname not in self._robots_fetch_tasks:
            self._robots_fetch_tasks[hostname] = asyncio.create_task(self._fetch_robots_txt(hostname))
        try:
            await asyncio.wait_for(self._robots_fetch_tasks[hostname], timeout=3)
        except asyncio.TimeoutError:
            pass

    def should_enqueue_url(self, url: str, check_robots: bool = True) -> bool:
        """Check if a URL should be enqueued for crawling."""
        if not url or url in self.visited or url in self.to_visit:
            return False

        parsed_url = urlparse(url)
        if parsed_url.scheme not in ('http', 'https') or not parsed_url.netloc:
            return False

        host = parsed_url.netloc.lower()
        
        # Check excluded subdomains
        if any(host == sub or host.endswith('.' + sub) for sub in self.excluded_subdomains):
            return False

        # Check excluded patterns
        # Supported types: regex, prefix, suffix, contains, exact
        if hasattr(self.config, 'excluded_patterns') and self.config.excluded_patterns:
            for pattern_config in self.config.excluded_patterns:
                p_type = pattern_config.get('type', 'contains')
                pattern = pattern_config.get('pattern', '')
                
                if not pattern:
                    continue
                    
                match = False
                try:
                    if p_type == 'regex':
                        import re
                        if re.search(pattern, url):
                            match = True
                    elif p_type == 'prefix':
                        if url.startswith(pattern):
                            match = True
                    elif p_type == 'suffix':
                        if url.endswith(pattern):
                            match = True
                    elif p_type == 'exact':
                        if url == pattern:
                            match = True
                    else: # contains
                        if pattern in url:
                            match = True
                            
                    if match:
                        logger.debug(f"URL {url} matched exclusion pattern: {pattern} ({p_type})")
                        return False
                except Exception as e:
                    logger.warning(f"Error checking exclusion pattern {pattern}: {e}")

        # Check allowed domains
        if self.allowed_domains and not any(host == domain or host.endswith('.' + domain) for domain in self.allowed_domains):
            return False

        # Check robots.txt
        if check_robots:
            parser = self.robot_parsers.get(parsed_url.netloc)
            if parser and not parser.is_allowed('*', url):
                return False

        return True

    @retry(stop=3, wait=2)
    async def _fetch_page(self, page: Page, url: str) -> Optional[Response]:
        """Fetch a page with retry logic."""
        logger.debug(f"Fetching page: {url}")
        return await page.goto(url, timeout=self.config.timeout * 1000, wait_until="domcontentloaded")

    async def handle_dynamic_content(self, page: Page) -> Dict:
        """
        Handle dynamic content loading using the advanced DynamicContentHandler.

        Returns:
            Dictionary with dynamic content processing results
        """
        results = {}

        try:
            # Use the advanced dynamic content handler if enabled
            if self.dynamic_config.infinite_scroll_enabled or self.dynamic_config.lazy_load_images:
                results = await self.dynamic_handler.process_page(page)
                logger.debug(f"Dynamic content handler results: {results}")
            else:
                # Fallback to basic dynamic scrolling
                for _ in range(self.config.dynamic_scroll_count):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(self.config.dynamic_scroll_delay)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=4000)
                    except PlaywrightTimeoutError:
                        await asyncio.sleep(1)

            # Always handle dynamic click selectors (custom user configuration)
            for selector in self.config.dynamic_click_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        if await element.is_visible():
                            await element.click(delay=self.config.dynamic_action_delay * 1000)
                            await asyncio.sleep(self.config.dynamic_action_delay)
                except Exception as e:
                    logger.warning(f"Could not click selector '{selector}': {e}")

        except Exception as e:
            logger.error(f"Error in handle_dynamic_content: {e}")

        return results

    async def handle_page(self, url: str) -> Optional[int]:
        """Process a single HTML page."""
        page: Optional[Page] = None
        status = 0

        try:
            async with self.fetch_semaphore:
                page = await self.context.new_page()
                if self.stealth_script:
                    await page.add_init_script(self.stealth_script)

                response = await self._fetch_page(page, url)
                if not response:
                    return status

                status = response.status
                final_url = response.url

                if status >= 400:
                    self.stats['http_errors'][status] += 1
                    return status

                # Handle dynamic content
                await self.handle_dynamic_content(page)

                # Wait for network to settle (Hybrid Wait Strategy)
                # Try networkidle for SPA support, but don't fail if tracking pixels keep connection open
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    logger.debug(f"Network idle timeout for {url} - proceeding with domcontentloaded")
                    # Fallback: Just wait a small buffer time
                    await asyncio.sleep(1)

                # Explicit delay if configured (Fix for slow loading SPAs)
                if self.config.delay_before_return_html > 0:
                    logger.debug(f"Waiting {self.config.delay_before_return_html}s before extracting content for {url}")
                    await asyncio.sleep(self.config.delay_before_return_html)

                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')

                # Validate page content
                page_title = soup.title.string.lower() if soup.title else ''
                page_body_text = soup.body.get_text().lower() if soup.body else ''
                
                if 'page not found' in page_title or '404' in page_title or 'page not found' in page_body_text:
                    logger.warning(f"Skipping 'Page Not Found' error page: {url}")
                    self.stats['pages_skipped_not_found'] += 1
                    return status

                if not soup.body or not soup.body.get_text(strip=True):
                    logger.info(f"Skipping empty page: {url}")
                    self.stats['pages_skipped_empty'] += 1
                    return status

                # Update stats
                self.stats['pages_fetched'] += 1
                self.stats['bytes_downloaded'] += len(html_content.encode('utf-8'))

                # Process content (streaming or file-based)
                if self.on_page_callback:
                    try:
                        await self.on_page_callback(final_url, html_content)
                    except Exception:
                        logger.exception("on_page_callback failed for %s", final_url)
                else:
                    # Save to file
                    html_hash = hashlib.sha1(str(url).encode()).hexdigest()
                    output_file = os.path.join(self.config.output_dir, f"{html_hash}.html")
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    self.url_mapping[str(final_url)] = output_file

                # Extract and enqueue links
                await self.enqueue_links_from_page(page, final_url)

            return status

        except Exception as e:
            logger.error(f"Error handling page {url}: {e}", exc_info=True)
            raise
        finally:
            if page and not page.is_closed():
                await page.close()
            self.visited.add(str(url))

    async def enqueue_links_from_page(self, page: Page, current_url: str):
        """Extract and enqueue links from a page."""
        links = await page.evaluate('''
            () => {
                const results = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    if (a.href) results.push(a.href);
                });
                return [...new Set(results)];
            }
        ''')
        
        for link in links:
            abs_url = urljoin(current_url, link)
            if self.should_enqueue_url(abs_url) and len(self.visited) < self.config.max_pages:
                self.to_visit.append(abs_url)

    async def run(self):
        """Main crawling loop."""
        await self._initialize_resources()

        if self.start_url and self.start_url not in self.visited:
            self.to_visit.append(self.start_url)

        while (self.to_visit or self.tasks) and len(self.visited) < self.config.max_pages:
            while self.to_visit and len(self.tasks) < self.config.fetch_concurrency:
                url = self.to_visit.popleft()
                if url in self.visited:
                    continue

                self.visited.add(url)
                hostname = urlparse(url).netloc
                
                # Set up rate limiting for this host
                if hostname not in self.host_limiters:
                    self.host_limiters[hostname] = AsyncLimiter(1, self.config.default_delay)
                
                # Ensure robots.txt is fetched
                await self.ensure_robots_rules(hostname)
                
                task = asyncio.create_task(self.process_url(url, hostname))
                self.tasks.add(task)

            done, pending = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
            self.tasks = pending

            for task in done:
                try:
                    await task
                except Exception:
                    pass  # Errors are logged within the task

    async def process_url(self, url: str, hostname: str):
        """Process a URL with rate limiting."""
        async with self.host_limiters[hostname]:
            await self.handle_page(url)

    async def close(self):
        """Clean up resources."""
        logger.info("Closing crawler resources...")
        
        if self.tasks:
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        
        if self.browser and self.browser.is_connected():
            await self.browser.close()
        
        if self.p:
            await self.p.stop()
        
        logger.info("Crawler resources closed.")

    def print_stats(self):
        """Print crawling statistics."""
        logger.info("--- Crawl Statistics ---")
        self.stats['total_urls_visited'] = len(self.visited)
        for key, value in sorted(self.stats.items()):
            logger.info(f"{key.replace('_', ' ').title():<30}: {value}")
        logger.info("------------------------")
