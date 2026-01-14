"""
Advanced dynamic content handler for web scraping.
Handles infinite scroll, Shadow DOM, lazy loading, and SPA detection.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DynamicContentConfig:
    """Configuration for dynamic content handling."""
    infinite_scroll_enabled: bool = True  # Bug #14 fix: Enable by default
    infinite_scroll_max_scrolls: int = 20
    shadow_dom_traversal: bool = True  # Enable Shadow DOM traversal
    lazy_load_images: bool = True
    scroll_stability_checks: int = 3
    scroll_wait_time: float = 1.0
    scroll_step_pixels: int = 500
    lazy_load_timeout: float = 2.0
    dynamic_content_wait: float = 5.0  # Timeout for dynamic content loading
    expand_collapsed_content: bool = True  # Expand accordions and details


class DynamicContentHandler:
    """
    Advanced handler for dynamic web content.
    Works with Playwright page objects to handle SPAs, infinite scroll,
    Shadow DOM, and lazy loading.
    """

    def __init__(self, config: Optional[DynamicContentConfig] = None):
        self.config = config or DynamicContentConfig()
        self.stats = {
            "pages_processed": 0,
            "infinite_scroll_detected": 0,
            "shadow_dom_elements_found": 0,
            "lazy_images_loaded": 0,
            "spa_pages_detected": 0
        }
        logger.info("DynamicContentHandler initialized")

    async def scroll_until_stable(
        self,
        page,
        max_scrolls: int = None,
        stability_checks: int = None,
        scroll_wait_time: float = None
    ) -> Tuple[int, int]:
        """
        Scroll the page until DOM height stops changing.

        Args:
            page: Playwright page object
            max_scrolls: Maximum number of scroll operations
            stability_checks: Number of stable height checks before stopping
            scroll_wait_time: Wait time between scrolls in seconds

        Returns:
            Tuple of (final_height, scroll_count)
        """
        max_scrolls = max_scrolls or self.config.infinite_scroll_max_scrolls
        stability_checks = stability_checks or self.config.scroll_stability_checks
        scroll_wait_time = scroll_wait_time or self.config.scroll_wait_time

        try:
            scroll_count = 0
            stable_count = 0
            last_height = 0

            for i in range(max_scrolls):
                # Get current scroll height
                current_height = await page.evaluate("document.body.scrollHeight")

                if current_height == last_height:
                    stable_count += 1
                    if stable_count >= stability_checks:
                        logger.info(f"Scroll stabilized at height {current_height} after {scroll_count} scrolls")
                        break
                else:
                    stable_count = 0
                    last_height = current_height

                # Scroll to bottom
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_count += 1

                # Wait for content to load
                await asyncio.sleep(scroll_wait_time)

                # Try to wait for network idle briefly
                try:
                    await page.wait_for_load_state("networkidle", timeout=2000)
                except Exception:
                    pass  # Continue even if timeout

            final_height = await page.evaluate("document.body.scrollHeight")
            logger.info(f"Completed scrolling: {scroll_count} scrolls, final height: {final_height}")

            # Scroll back to top for consistent content extraction
            await page.evaluate("window.scrollTo(0, 0)")

            return final_height, scroll_count

        except Exception as e:
            logger.error(f"Error during scroll_until_stable: {e}")
            return 0, 0

    async def detect_infinite_scroll(self, page) -> bool:
        """
        Detect if the page uses infinite scroll pattern.

        Args:
            page: Playwright page object

        Returns:
            True if infinite scroll is detected
        """
        try:
            # Check for common infinite scroll indicators
            indicators = await page.evaluate("""
                () => {
                    const indicators = {
                        hasIntersectionObserver: false,
                        hasScrollEventListener: false,
                        hasLoadMoreButton: false,
                        hasPaginationMarker: false,
                        hasInfiniteScrollClass: false
                    };

                    // Check for IntersectionObserver usage (common in infinite scroll)
                    // This is a heuristic - can't directly detect observer usage
                    indicators.hasIntersectionObserver = typeof IntersectionObserver !== 'undefined';

                    // Check for load more / show more buttons
                    const loadMoreSelectors = [
                        'button[class*="load-more"]',
                        'button[class*="show-more"]',
                        'a[class*="load-more"]',
                        '[data-testid*="load-more"]',
                        '.load-more',
                        '.show-more',
                        '#load-more'
                    ];

                    for (const selector of loadMoreSelectors) {
                        if (document.querySelector(selector)) {
                            indicators.hasLoadMoreButton = true;
                            break;
                        }
                    }

                    // Check for infinite scroll class names
                    const infiniteScrollSelectors = [
                        '[class*="infinite-scroll"]',
                        '[class*="infinitescroll"]',
                        '[data-infinite-scroll]',
                        '[data-infinite]'
                    ];

                    for (const selector of infiniteScrollSelectors) {
                        if (document.querySelector(selector)) {
                            indicators.hasInfiniteScrollClass = true;
                            break;
                        }
                    }

                    // Check for pagination markers
                    const paginationSelectors = [
                        '[class*="pagination"]',
                        '.pager',
                        '[aria-label*="pagination"]'
                    ];

                    for (const selector of paginationSelectors) {
                        if (document.querySelector(selector)) {
                            indicators.hasPaginationMarker = true;
                            break;
                        }
                    }

                    return indicators;
                }
            """)

            is_infinite_scroll = (
                indicators.get("hasInfiniteScrollClass", False) or
                indicators.get("hasLoadMoreButton", False)
            )

            if is_infinite_scroll:
                self.stats["infinite_scroll_detected"] += 1
                logger.info(f"Infinite scroll detected: {indicators}")

            return is_infinite_scroll

        except Exception as e:
            logger.error(f"Error detecting infinite scroll: {e}")
            return False

    async def extract_shadow_dom_content(self, page) -> List[Dict[str, Any]]:
        """
        Extract content from Shadow DOM elements.

        Args:
            page: Playwright page object

        Returns:
            List of dictionaries containing shadow DOM content
        """
        if not self.config.shadow_dom_traversal:
            return []

        try:
            shadow_content = await page.evaluate("""
                () => {
                    const shadowContents = [];

                    function extractFromShadowRoot(root, path = []) {
                        const elements = root.querySelectorAll('*');

                        for (const el of elements) {
                            if (el.shadowRoot) {
                                const shadowPath = [...path, el.tagName.toLowerCase()];
                                const content = {
                                    path: shadowPath.join(' > '),
                                    tagName: el.tagName.toLowerCase(),
                                    textContent: '',
                                    innerHTML: ''
                                };

                                // Get text content from shadow root
                                content.textContent = el.shadowRoot.textContent?.trim() || '';
                                content.innerHTML = el.shadowRoot.innerHTML?.substring(0, 5000) || '';

                                if (content.textContent.length > 0) {
                                    shadowContents.push(content);
                                }

                                // Recursively check nested shadow roots
                                extractFromShadowRoot(el.shadowRoot, shadowPath);
                            }
                        }
                    }

                    // Start from document body
                    extractFromShadowRoot(document.body);

                    return shadowContents;
                }
            """)

            if shadow_content:
                self.stats["shadow_dom_elements_found"] += len(shadow_content)
                logger.info(f"Extracted {len(shadow_content)} Shadow DOM elements")

            return shadow_content

        except Exception as e:
            logger.error(f"Error extracting Shadow DOM content: {e}")
            return []

    async def handle_lazy_images(self, page) -> int:
        """
        Trigger lazy loading for images by scrolling them into view.

        Args:
            page: Playwright page object

        Returns:
            Number of images that were lazy loaded
        """
        if not self.config.lazy_load_images:
            return 0

        try:
            lazy_loaded_count = await page.evaluate("""
                async () => {
                    let loadedCount = 0;

                    // Find lazy-loadable images
                    const lazySelectors = [
                        'img[loading="lazy"]',
                        'img[data-src]',
                        'img[data-lazy]',
                        'img.lazy',
                        'img.lazyload',
                        'img[data-srcset]'
                    ];

                    const lazyImages = [];
                    for (const selector of lazySelectors) {
                        const imgs = document.querySelectorAll(selector);
                        imgs.forEach(img => {
                            if (!lazyImages.includes(img)) {
                                lazyImages.push(img);
                            }
                        });
                    }

                    // Scroll each lazy image into view
                    for (const img of lazyImages) {
                        try {
                            img.scrollIntoView({ behavior: 'instant', block: 'center' });

                            // If image has data-src, try to trigger loading
                            if (img.dataset.src && !img.src) {
                                img.src = img.dataset.src;
                                loadedCount++;
                            }

                            // Wait a bit for loading
                            await new Promise(r => setTimeout(r, 100));
                        } catch (e) {
                            // Continue with next image
                        }
                    }

                    // Scroll back to top
                    window.scrollTo(0, 0);

                    return loadedCount;
                }
            """)

            # Wait for images to finish loading
            await asyncio.sleep(self.config.lazy_load_timeout)

            self.stats["lazy_images_loaded"] += lazy_loaded_count
            if lazy_loaded_count > 0:
                logger.info(f"Triggered lazy loading for {lazy_loaded_count} images")

            return lazy_loaded_count

        except Exception as e:
            logger.error(f"Error handling lazy images: {e}")
            return 0

    async def detect_spa_type(self, page) -> str:
        """
        Detect the type of Single Page Application routing.

        Args:
            page: Playwright page object

        Returns:
            "hash" for hash-based routing, "history" for HTML5 history API,
            "none" if no SPA detected
        """
        try:
            spa_info = await page.evaluate("""
                () => {
                    const info = {
                        hasHashRouting: false,
                        hasHistoryAPI: false,
                        frameworkHints: [],
                        currentHash: window.location.hash,
                        hasRouterElements: false
                    };

                    // Check current URL for hash routing
                    if (window.location.hash && window.location.hash.length > 1) {
                        // Hash contains more than just #
                        if (window.location.hash.includes('/')) {
                            info.hasHashRouting = true;
                        }
                    }

                    // Check for common SPA framework indicators
                    const frameworkIndicators = {
                        'React': ['__REACT_DEVTOOLS_GLOBAL_HOOK__', '_reactRootContainer'],
                        'Vue': ['__VUE__', '__VUE_DEVTOOLS_GLOBAL_HOOK__'],
                        'Angular': ['ng-version', 'getAllAngularRootElements'],
                        'Svelte': ['__svelte'],
                        'Next.js': ['__NEXT_DATA__'],
                        'Nuxt': ['__NUXT__']
                    };

                    for (const [framework, indicators] of Object.entries(frameworkIndicators)) {
                        for (const indicator of indicators) {
                            if (window[indicator] || document.querySelector(`[${indicator}]`)) {
                                info.frameworkHints.push(framework);
                                break;
                            }
                        }
                    }

                    // Check for router-specific elements
                    const routerSelectors = [
                        'router-outlet',
                        'router-view',
                        '[data-router]',
                        '#app[data-v-app]'
                    ];

                    for (const selector of routerSelectors) {
                        if (document.querySelector(selector)) {
                            info.hasRouterElements = true;
                            break;
                        }
                    }

                    // Check if history API is being used
                    // This is a heuristic - we check if pushState has been called
                    // by looking for common SPA patterns
                    if (info.frameworkHints.length > 0 && !info.hasHashRouting) {
                        info.hasHistoryAPI = true;
                    }

                    return info;
                }
            """)

            spa_type = "none"

            if spa_info.get("hasHashRouting"):
                spa_type = "hash"
            elif spa_info.get("hasHistoryAPI") or spa_info.get("frameworkHints"):
                spa_type = "history"

            if spa_type != "none":
                self.stats["spa_pages_detected"] += 1
                logger.info(f"SPA detected: type={spa_type}, frameworks={spa_info.get('frameworkHints', [])}")

            return spa_type

        except Exception as e:
            logger.error(f"Error detecting SPA type: {e}")
            return "none"

    async def wait_for_dynamic_content(self, page, timeout: float = 5.0) -> bool:
        """
        Wait for dynamic content to finish loading.

        Args:
            page: Playwright page object
            timeout: Maximum wait time in seconds

        Returns:
            True if content appears stable
        """
        try:
            # Wait for network to be idle
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            except Exception:
                logger.debug("Network idle timeout, continuing...")

            # Wait for DOM to be stable
            stable = await page.evaluate("""
                async () => {
                    return new Promise((resolve) => {
                        let mutations = 0;
                        const observer = new MutationObserver(() => {
                            mutations++;
                        });

                        observer.observe(document.body, {
                            childList: true,
                            subtree: true,
                            attributes: true
                        });

                        // Check stability after 1 second
                        setTimeout(() => {
                            observer.disconnect();
                            resolve(mutations < 10);  // Consider stable if less than 10 mutations
                        }, 1000);
                    });
                }
            """)

            return stable

        except Exception as e:
            logger.error(f"Error waiting for dynamic content: {e}")
            return True  # Assume stable on error

    async def expand_collapsed_content(self, page) -> int:
        """
        Click on expandable/collapsible elements to reveal hidden content.

        Args:
            page: Playwright page object

        Returns:
            Number of elements expanded
        """
        try:
            expanded_count = await page.evaluate("""
                async () => {
                    let expandedCount = 0;

                    // Common expandable element selectors
                    const expandableSelectors = [
                        '[aria-expanded="false"]',
                        '.collapsed:not(.expanded)',
                        '.accordion-toggle:not(.active)',
                        '[data-toggle="collapse"]:not(.show)',
                        '.expand-button',
                        '.show-more:not(.clicked)',
                        'details:not([open])'
                    ];

                    for (const selector of expandableSelectors) {
                        const elements = document.querySelectorAll(selector);

                        for (const el of elements) {
                            try {
                                // Handle <details> elements
                                if (el.tagName === 'DETAILS') {
                                    el.setAttribute('open', '');
                                    expandedCount++;
                                } else {
                                    el.click();
                                    expandedCount++;
                                }

                                // Brief wait between clicks
                                await new Promise(r => setTimeout(r, 200));
                            } catch (e) {
                                // Continue with next element
                            }
                        }
                    }

                    return expandedCount;
                }
            """)

            if expanded_count > 0:
                logger.info(f"Expanded {expanded_count} collapsed content sections")

                # Wait for expanded content to render
                await asyncio.sleep(0.5)

            return expanded_count

        except Exception as e:
            logger.error(f"Error expanding collapsed content: {e}")
            return 0

    async def process_page(self, page) -> Dict[str, Any]:
        """
        Process a page with all dynamic content handling.

        Args:
            page: Playwright page object

        Returns:
            Dictionary with processing results and extracted content
        """
        results = {
            "spa_type": "none",
            "infinite_scroll": False,
            "shadow_dom_content": [],
            "lazy_images_loaded": 0,
            "expanded_sections": 0,
            "final_scroll_height": 0,
            "scroll_count": 0
        }

        try:
            self.stats["pages_processed"] += 1

            # Detect SPA type
            results["spa_type"] = await self.detect_spa_type(page)

            # Wait for initial dynamic content
            await self.wait_for_dynamic_content(page)

            # Handle lazy loading images first
            results["lazy_images_loaded"] = await self.handle_lazy_images(page)

            # Detect and handle infinite scroll
            results["infinite_scroll"] = await self.detect_infinite_scroll(page)
            if results["infinite_scroll"] and self.config.infinite_scroll_enabled:
                height, scrolls = await self.scroll_until_stable(page)
                results["final_scroll_height"] = height
                results["scroll_count"] = scrolls

            # Expand collapsed content
            results["expanded_sections"] = await self.expand_collapsed_content(page)

            # Extract Shadow DOM content
            results["shadow_dom_content"] = await self.extract_shadow_dom_content(page)

            logger.info(f"Dynamic content processing complete: {results}")

            return results

        except Exception as e:
            logger.error(f"Error in process_page: {e}")
            return results

    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics."""
        return self.stats.copy()
