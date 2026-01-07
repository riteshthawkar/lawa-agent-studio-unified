"""
Content preprocessing module for cleaning and tokenizing content before embedding.
Handles media tokenization, URL tokenization, boilerplate removal, script/style removal,
and gibberish/spam detection.
"""

import re
import logging
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from collections import Counter
from bs4 import BeautifulSoup
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class GibberishDetector:
    """
    Bug #22 fix: Detect gibberish, spam, and low-quality content.
    Uses multiple heuristics to identify content that shouldn't be embedded.
    """

    def __init__(
        self,
        min_word_length: float = 2.0,
        max_word_length: float = 20.0,
        min_unique_word_ratio: float = 0.15,
        max_repeated_char_ratio: float = 0.3,
        min_alpha_ratio: float = 0.5,
        max_special_char_ratio: float = 0.3,
        min_content_length: int = 50
    ):
        """
        Initialize gibberish detector with configurable thresholds.

        Args:
            min_word_length: Minimum average word length (short words = gibberish)
            max_word_length: Maximum average word length (long words = gibberish)
            min_unique_word_ratio: Minimum ratio of unique words (repetition = spam)
            max_repeated_char_ratio: Maximum ratio of repeated characters
            min_alpha_ratio: Minimum ratio of alphabetic characters
            max_special_char_ratio: Maximum ratio of special characters
            min_content_length: Minimum content length to analyze
        """
        self.min_word_length = min_word_length
        self.max_word_length = max_word_length
        self.min_unique_word_ratio = min_unique_word_ratio
        self.max_repeated_char_ratio = max_repeated_char_ratio
        self.min_alpha_ratio = min_alpha_ratio
        self.max_special_char_ratio = max_special_char_ratio
        self.min_content_length = min_content_length

        # Common gibberish patterns
        self.gibberish_patterns = [
            r'(.)\1{5,}',  # Same character repeated 5+ times
            r'\b[bcdfghjklmnpqrstvwxyz]{6,}\b',  # 6+ consonants in a row (no vowels)
            r'\b[\d]{10,}\b',  # Long number sequences
            r'lorem ipsum',  # Placeholder text
            r'test\s*test\s*test',  # Test repetition
            r'asdf|qwerty|zxcv',  # Keyboard mashing
        ]
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.gibberish_patterns]

    def analyze(self, content: str) -> Dict[str, Any]:
        """
        Analyze content for gibberish indicators.

        Returns:
            Dict with analysis results and quality score (0-100)
        """
        if not content or len(content) < self.min_content_length:
            return {
                "is_gibberish": False,
                "quality_score": 50,  # Neutral for short content
                "reason": "Content too short to analyze",
                "metrics": {}
            }

        # Clean content for analysis
        clean_content = self._normalize_content(content)
        words = clean_content.split()

        if not words:
            return {
                "is_gibberish": True,
                "quality_score": 0,
                "reason": "No valid words found",
                "metrics": {}
            }

        metrics = self._calculate_metrics(clean_content, words)
        is_gibberish, reason = self._evaluate_metrics(metrics)
        quality_score = self._calculate_quality_score(metrics, is_gibberish)

        return {
            "is_gibberish": is_gibberish,
            "quality_score": quality_score,
            "reason": reason,
            "metrics": metrics
        }

    def _normalize_content(self, content: str) -> str:
        """Normalize content for analysis."""
        # Remove markdown formatting
        clean = re.sub(r'\[.*?\]\(.*?\)', '', content)  # Remove links
        clean = re.sub(r'[#*_`~]', '', clean)  # Remove formatting chars
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def _calculate_metrics(self, content: str, words: List[str]) -> Dict[str, float]:
        """Calculate various metrics for gibberish detection."""
        # Word-level metrics
        word_lengths = [len(w) for w in words]
        avg_word_length = sum(word_lengths) / len(words) if words else 0
        unique_words = set(w.lower() for w in words)
        unique_word_ratio = len(unique_words) / len(words) if words else 0

        # Character-level metrics
        total_chars = len(content)
        alpha_chars = sum(1 for c in content if c.isalpha())
        special_chars = sum(1 for c in content if not c.isalnum() and not c.isspace())

        alpha_ratio = alpha_chars / total_chars if total_chars else 0
        special_char_ratio = special_chars / total_chars if total_chars else 0

        # Repeated character analysis
        char_counts = Counter(content.lower())
        most_common_char_count = char_counts.most_common(1)[0][1] if char_counts else 0
        repeated_char_ratio = most_common_char_count / total_chars if total_chars else 0

        # Pattern matching
        pattern_matches = sum(1 for p in self.compiled_patterns if p.search(content))

        return {
            "avg_word_length": avg_word_length,
            "unique_word_ratio": unique_word_ratio,
            "alpha_ratio": alpha_ratio,
            "special_char_ratio": special_char_ratio,
            "repeated_char_ratio": repeated_char_ratio,
            "pattern_matches": pattern_matches,
            "word_count": len(words),
            "unique_word_count": len(unique_words)
        }

    def _evaluate_metrics(self, metrics: Dict[str, float]) -> Tuple[bool, str]:
        """Evaluate metrics to determine if content is gibberish."""
        reasons = []

        # Check average word length
        if metrics["avg_word_length"] < self.min_word_length:
            reasons.append("Average word length too short")
        elif metrics["avg_word_length"] > self.max_word_length:
            reasons.append("Average word length too long")

        # Check unique word ratio (spam detection)
        if metrics["unique_word_ratio"] < self.min_unique_word_ratio:
            reasons.append("Too many repeated words (possible spam)")

        # Check character ratios
        if metrics["alpha_ratio"] < self.min_alpha_ratio:
            reasons.append("Too few alphabetic characters")

        if metrics["special_char_ratio"] > self.max_special_char_ratio:
            reasons.append("Too many special characters")

        if metrics["repeated_char_ratio"] > self.max_repeated_char_ratio:
            reasons.append("Too many repeated characters")

        # Check pattern matches
        if metrics["pattern_matches"] >= 2:
            reasons.append("Multiple gibberish patterns detected")

        is_gibberish = len(reasons) >= 2  # Need at least 2 indicators
        reason = "; ".join(reasons) if reasons else "Content appears valid"

        return is_gibberish, reason

    def _calculate_quality_score(self, metrics: Dict[str, float], is_gibberish: bool) -> int:
        """Calculate a quality score from 0-100."""
        if is_gibberish:
            return max(0, 30 - (metrics.get("pattern_matches", 0) * 10))

        score = 70  # Base score

        # Adjust based on metrics
        if metrics["unique_word_ratio"] > 0.4:
            score += 10
        elif metrics["unique_word_ratio"] < 0.2:
            score -= 15

        if 3.0 <= metrics["avg_word_length"] <= 8.0:
            score += 10

        if metrics["alpha_ratio"] > 0.7:
            score += 10

        return min(100, max(0, score))


@dataclass
class PreprocessorConfig:
    """Configuration for content preprocessing pipeline."""
    # All enabled by default per user decision
    enable_script_style_removal: bool = True
    enable_media_tokenizer: bool = True
    enable_url_tokenizer: bool = True
    enable_boilerplate_removal: bool = True
    enable_gibberish_detection: bool = True  # Bug #22 fix: Enable gibberish detection
    custom_boilerplate_selectors: List[str] = field(default_factory=list)
    preserve_alt_text: bool = True  # Keep image alt text as context
    gibberish_quality_threshold: int = 30  # Content below this score is flagged


class ScriptStyleRemover:
    """Remove script, style, and noscript tags from content."""

    # Tags to completely remove
    REMOVE_TAGS = ['script', 'style', 'noscript', 'template']

    def process(self, content: str, content_type: str = "html") -> str:
        """
        Remove script and style tags from content.

        Args:
            content: HTML or Markdown content
            content_type: "html" or "markdown"

        Returns:
            Cleaned content with script/style tags removed
        """
        if content_type == "markdown":
            # For markdown, remove inline HTML script/style tags
            return self._remove_from_markdown(content)
        else:
            return self._remove_from_html(content)

    def _remove_from_html(self, html_content: str) -> str:
        """Remove script/style tags from HTML."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Remove all script, style, noscript, template tags
            for tag in soup.find_all(self.REMOVE_TAGS):
                tag.decompose()

            return str(soup)
        except Exception as e:
            logger.error(f"Error removing script/style from HTML: {e}")
            return html_content

    def _remove_from_markdown(self, markdown_content: str) -> str:
        """Remove inline HTML script/style from markdown."""
        try:
            # Remove <script>...</script> blocks
            content = re.sub(
                r'<script[^>]*>.*?</script>',
                '',
                markdown_content,
                flags=re.DOTALL | re.IGNORECASE
            )

            # Remove <style>...</style> blocks
            content = re.sub(
                r'<style[^>]*>.*?</style>',
                '',
                content,
                flags=re.DOTALL | re.IGNORECASE
            )

            # Remove <noscript>...</noscript> blocks
            content = re.sub(
                r'<noscript[^>]*>.*?</noscript>',
                '',
                content,
                flags=re.DOTALL | re.IGNORECASE
            )

            return content
        except Exception as e:
            logger.error(f"Error removing script/style from markdown: {e}")
            return markdown_content


class MediaTokenizer:
    """Replace media tags with tokens to prevent embedding pollution."""

    # Token mappings for different media types
    MEDIA_TOKENS = {
        'img': '[IMAGE]',
        'video': '[VIDEO]',
        'audio': '[AUDIO]',
        'svg': '[SVG]',
        'canvas': '[CANVAS]',
        'iframe': '[IFRAME]',
        'embed': '[EMBED]',
        'object': '[OBJECT]',
        'picture': '[PICTURE]',
        'source': '',  # Remove source tags entirely
        'track': '',   # Remove track tags entirely
    }

    def __init__(self, preserve_alt_text: bool = True):
        self.preserve_alt_text = preserve_alt_text

    def process(self, content: str, content_type: str = "html") -> Tuple[str, Dict[str, List[Dict]]]:
        """
        Replace media tags with tokens.

        Args:
            content: HTML or Markdown content
            content_type: "html" or "markdown"

        Returns:
            Tuple of (processed_content, extracted_media_metadata)
        """
        if content_type == "markdown":
            return self._process_markdown(content)
        else:
            return self._process_html(content)

    def _process_html(self, html_content: str) -> Tuple[str, Dict[str, List[Dict]]]:
        """Process HTML content and replace media tags with tokens."""
        extracted_media = {
            'images': [],
            'videos': [],
            'audio': [],
            'svgs': [],
            'iframes': [],
            'other': []
        }

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Process each media type
            for tag_name, token in self.MEDIA_TOKENS.items():
                for tag in soup.find_all(tag_name):
                    media_info = self._extract_media_info(tag, tag_name)

                    # Store media info
                    category = self._get_category(tag_name)
                    extracted_media[category].append(media_info)

                    # Replace with token (preserve alt text if configured)
                    replacement_text = token
                    if self.preserve_alt_text and tag_name == 'img':
                        alt_text = tag.get('alt', '').strip()
                        if alt_text:
                            replacement_text = f"{token}: {alt_text}"

                    if token:
                        tag.replace_with(replacement_text)
                    else:
                        tag.decompose()

            return str(soup), extracted_media

        except Exception as e:
            logger.error(f"Error tokenizing media in HTML: {e}")
            return html_content, extracted_media

    def _process_markdown(self, markdown_content: str) -> Tuple[str, Dict[str, List[Dict]]]:
        """Process markdown content and replace media references with tokens."""
        extracted_media = {
            'images': [],
            'videos': [],
            'audio': [],
            'svgs': [],
            'iframes': [],
            'other': []
        }

        try:
            content = markdown_content

            # Replace markdown image syntax: ![alt](url)
            img_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
            for match in re.finditer(img_pattern, content):
                alt_text = match.group(1)
                url = match.group(2)
                extracted_media['images'].append({'alt': alt_text, 'src': url})

            if self.preserve_alt_text:
                content = re.sub(
                    img_pattern,
                    lambda m: f"[IMAGE]: {m.group(1)}" if m.group(1) else "[IMAGE]",
                    content
                )
            else:
                content = re.sub(img_pattern, "[IMAGE]", content)

            # Replace inline HTML media tags in markdown
            for tag_name, token in self.MEDIA_TOKENS.items():
                if not token:
                    # Remove completely
                    content = re.sub(
                        rf'<{tag_name}[^>]*>.*?</{tag_name}>',
                        '',
                        content,
                        flags=re.DOTALL | re.IGNORECASE
                    )
                    content = re.sub(
                        rf'<{tag_name}[^>]*/?>',
                        '',
                        content,
                        flags=re.IGNORECASE
                    )
                else:
                    # Replace with token
                    content = re.sub(
                        rf'<{tag_name}[^>]*>.*?</{tag_name}>',
                        token,
                        content,
                        flags=re.DOTALL | re.IGNORECASE
                    )
                    content = re.sub(
                        rf'<{tag_name}[^>]*/?>',
                        token,
                        content,
                        flags=re.IGNORECASE
                    )

            return content, extracted_media

        except Exception as e:
            logger.error(f"Error tokenizing media in markdown: {e}")
            return markdown_content, extracted_media

    def _extract_media_info(self, tag, tag_name: str) -> Dict[str, Any]:
        """Extract relevant information from a media tag."""
        info = {
            'tag': tag_name,
            'src': tag.get('src', tag.get('href', '')),
            'alt': tag.get('alt', ''),
            'title': tag.get('title', ''),
        }

        # Additional attributes for specific media types
        if tag_name == 'video':
            info['poster'] = tag.get('poster', '')
        elif tag_name == 'iframe':
            info['src'] = tag.get('src', '')

        return info

    def _get_category(self, tag_name: str) -> str:
        """Get the category for storing extracted media info."""
        category_map = {
            'img': 'images',
            'picture': 'images',
            'video': 'videos',
            'audio': 'audio',
            'svg': 'svgs',
            'iframe': 'iframes',
        }
        return category_map.get(tag_name, 'other')


class URLTokenizer:
    """Replace URLs with tokens before embedding to prevent embedding pollution."""

    # URL pattern for matching
    URL_PATTERN = re.compile(
        r'https?://[^\s<>"\')\]]+|'
        r'www\.[^\s<>"\')\]]+',
        re.IGNORECASE
    )

    def process(self, content: str) -> Tuple[str, Dict[str, List[str]]]:
        """
        Replace URLs with [URL] tokens.

        Args:
            content: Text content (HTML or Markdown)

        Returns:
            Tuple of (processed_content, extracted_urls_metadata)
        """
        extracted_urls = {
            'urls': [],
            'url_count': 0
        }

        try:
            # Find all URLs
            urls = self.URL_PATTERN.findall(content)
            extracted_urls['urls'] = list(set(urls))  # Deduplicate
            extracted_urls['url_count'] = len(urls)

            # Replace URLs with token
            processed_content = self.URL_PATTERN.sub('[URL]', content)

            # Also handle markdown link syntax: [text](url)
            # Keep the link text, replace the URL
            md_link_pattern = r'\[([^\]]+)\]\([^)]+\)'
            processed_content = re.sub(
                md_link_pattern,
                r'[\1]([URL])',
                processed_content
            )

            logger.debug(f"Replaced {len(urls)} URLs with tokens")
            return processed_content, extracted_urls

        except Exception as e:
            logger.error(f"Error tokenizing URLs: {e}")
            return content, extracted_urls


class BoilerplateRemover:
    """Remove common boilerplate elements from web content."""

    # Default boilerplate selectors
    DEFAULT_BOILERPLATE_SELECTORS = [
        # Navigation and layout
        'nav', 'header', 'footer', 'aside',
        '.nav', '.navbar', '.navigation', '.menu',
        '.header', '.footer', '.sidebar',
        '#nav', '#header', '#footer', '#sidebar',
        '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',

        # Cookie/consent banners
        '.cookie-banner', '.cookie-consent', '.cookie-notice', '.cookie-popup',
        '.gdpr-banner', '.gdpr-consent', '.consent-banner', '.privacy-banner',
        '#cookie-banner', '#cookie-consent', '#gdpr-banner',
        '[class*="cookie"]', '[class*="consent"]',

        # Advertisements
        '.advertisement', '.ad', '.ads', '.advert', '.ad-container',
        '.google-ad', '.sponsored', '.promo-banner',
        '[class*="advertisement"]', '[id*="google_ads"]',

        # Social and sharing
        '.social-share', '.social-links', '.share-buttons', '.share-bar',
        '.social-icons', '.follow-buttons', '.social-widget',

        # Navigation elements
        '.breadcrumb', '.breadcrumbs', '.pagination', '.pager',

        # User interaction sections (not main content)
        '.comments', '.comment-section', '.comment-form', '.disqus',
        '.related-posts', '.related-articles', '.recommended',
        '.newsletter', '.subscribe', '.subscription-form', '.email-signup',

        # Modals, popups, dialogs (Bug #19 fix)
        '.modal', '.popup', '.popover', '.dialog', '.lightbox',
        '.overlay', '.backdrop', '.modal-backdrop', '.popup-overlay',
        '[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]',
        '.modal-content', '.popup-content', '.modal-wrapper',
        '#modal', '#popup', '#overlay',
        '[class*="modal"]', '[class*="popup"]', '[class*="dialog"]',

        # Forms (non-content forms)
        '.search-form', '.login-form', '.signup-form', '.contact-form',
        '.search-box', '.search-container', '.searchbar',
        '[role="search"]', 'form.search', 'form#search',

        # Chat widgets and support
        '.chat-widget', '.chat-button', '.chat-container', '.live-chat',
        '.intercom-container', '.drift-widget', '.zendesk-widget', '.crisp-widget',
        '.helpdesk-widget', '.support-widget', '.messenger-widget',
        '[class*="chat-widget"]', '[class*="live-chat"]', '[class*="intercom"]',
        '[class*="drift"]', '[class*="zendesk"]', '[class*="crisp"]',
        '#intercom-container', '#drift-widget', '#chat-widget',

        # Sticky elements and floating UI
        '.sticky-header', '.sticky-footer', '.fixed-header', '.fixed-footer',
        '.floating-action', '.fab', '.back-to-top', '.scroll-to-top',

        # Alerts and notifications
        '.alert-banner', '.notification-bar', '.announcement-bar', '.promo-bar',
        '.toast', '.snackbar', '[role="alert"]',
    ]

    def __init__(self, custom_selectors: Optional[List[str]] = None):
        self.selectors = self.DEFAULT_BOILERPLATE_SELECTORS.copy()
        if custom_selectors:
            self.selectors.extend(custom_selectors)

    def process(self, content: str, content_type: str = "html") -> str:
        """
        Remove boilerplate elements from content.

        Args:
            content: HTML or Markdown content
            content_type: "html" or "markdown"

        Returns:
            Content with boilerplate removed
        """
        if content_type == "markdown":
            # For markdown, we can only do limited boilerplate removal
            return self._process_markdown(content)
        else:
            return self._process_html(content)

    def _process_html(self, html_content: str) -> str:
        """Remove boilerplate elements from HTML."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Remove elements matching boilerplate selectors
            for selector in self.selectors:
                try:
                    for element in soup.select(selector):
                        element.decompose()
                except Exception as e:
                    # Some selectors might be invalid, skip them
                    logger.debug(f"Selector '{selector}' failed: {e}")
                    continue

            return str(soup)

        except Exception as e:
            logger.error(f"Error removing boilerplate from HTML: {e}")
            return html_content

    def _process_markdown(self, markdown_content: str) -> str:
        """Remove common boilerplate patterns from markdown."""
        try:
            content = markdown_content

            # Remove common navigation patterns
            # Remove lines that look like navigation menus (multiple links on one line)
            content = re.sub(
                r'^.*\[.*\]\(.*\).*\[.*\]\(.*\).*\[.*\]\(.*\).*$',
                '',
                content,
                flags=re.MULTILINE
            )

            # Remove "Skip to content" and similar accessibility links
            content = re.sub(
                r'^\s*\[Skip to .*?\]\(.*?\)\s*$',
                '',
                content,
                flags=re.MULTILINE | re.IGNORECASE
            )

            # Remove breadcrumb patterns (Home > Category > Page)
            content = re.sub(
                r'^.*(?:Home|Start).*>.*>.*$',
                '',
                content,
                flags=re.MULTILINE | re.IGNORECASE
            )

            # Remove social share patterns
            content = re.sub(
                r'^\s*(?:Share|Follow|Like|Tweet|Pin)[\s:]+.*$',
                '',
                content,
                flags=re.MULTILINE | re.IGNORECASE
            )

            # Remove cookie notice patterns
            content = re.sub(
                r'(?:This (?:website|site) uses cookies|We use cookies|Cookie (?:Policy|Notice|Consent)).*?(?:\n\n|\Z)',
                '',
                content,
                flags=re.DOTALL | re.IGNORECASE
            )

            # Clean up multiple empty lines
            content = re.sub(r'\n{3,}', '\n\n', content)

            return content.strip()

        except Exception as e:
            logger.error(f"Error removing boilerplate from markdown: {e}")
            return markdown_content


class ContentPreprocessor:
    """
    Main orchestrator for content preprocessing pipeline.
    Runs content through multiple preprocessing stages before embedding.
    """

    def __init__(self, config: Optional[PreprocessorConfig] = None):
        self.config = config or PreprocessorConfig()

        # Initialize preprocessors
        self.script_style_remover = ScriptStyleRemover()
        self.media_tokenizer = MediaTokenizer(
            preserve_alt_text=self.config.preserve_alt_text
        )
        self.url_tokenizer = URLTokenizer()
        self.boilerplate_remover = BoilerplateRemover(
            custom_selectors=self.config.custom_boilerplate_selectors
        )
        # Bug #22 fix: Initialize gibberish detector
        self.gibberish_detector = GibberishDetector()

        logger.info("ContentPreprocessor initialized with config: "
                   f"script_style={self.config.enable_script_style_removal}, "
                   f"media={self.config.enable_media_tokenizer}, "
                   f"url={self.config.enable_url_tokenizer}, "
                   f"boilerplate={self.config.enable_boilerplate_removal}, "
                   f"gibberish={self.config.enable_gibberish_detection}")

    def process(self, content: str, content_type: str = "html") -> Tuple[str, Dict[str, Any]]:
        """
        Process content through the preprocessing pipeline.

        Args:
            content: Raw content (HTML or Markdown)
            content_type: "html" or "markdown"

        Returns:
            Tuple of (processed_content, extracted_metadata)
        """
        metadata = {
            'original_length': len(content),
            'media': {},
            'urls': {},
            'preprocessing_applied': []
        }

        processed_content = content

        try:
            # Stage 1: Remove script and style tags
            if self.config.enable_script_style_removal:
                processed_content = self.script_style_remover.process(
                    processed_content, content_type
                )
                metadata['preprocessing_applied'].append('script_style_removal')

            # Stage 2: Remove boilerplate (before media tokenization)
            if self.config.enable_boilerplate_removal:
                processed_content = self.boilerplate_remover.process(
                    processed_content, content_type
                )
                metadata['preprocessing_applied'].append('boilerplate_removal')

            # Stage 3: Tokenize media elements
            if self.config.enable_media_tokenizer:
                processed_content, media_metadata = self.media_tokenizer.process(
                    processed_content, content_type
                )
                metadata['media'] = media_metadata
                metadata['preprocessing_applied'].append('media_tokenization')

            # Stage 4: Tokenize URLs (should be last to catch all remaining URLs)
            if self.config.enable_url_tokenizer:
                processed_content, url_metadata = self.url_tokenizer.process(
                    processed_content
                )
                metadata['urls'] = url_metadata
                metadata['preprocessing_applied'].append('url_tokenization')

            # Bug #22 fix: Stage 5 - Gibberish detection
            if self.config.enable_gibberish_detection:
                gibberish_result = self.gibberish_detector.analyze(processed_content)
                metadata['content_quality'] = {
                    'is_gibberish': gibberish_result['is_gibberish'],
                    'quality_score': gibberish_result['quality_score'],
                    'reason': gibberish_result['reason'],
                    'below_threshold': gibberish_result['quality_score'] < self.config.gibberish_quality_threshold
                }
                metadata['preprocessing_applied'].append('gibberish_detection')

                if gibberish_result['is_gibberish']:
                    logger.warning(f"Gibberish content detected: {gibberish_result['reason']}")

            # Record final length
            metadata['processed_length'] = len(processed_content)
            metadata['reduction_percent'] = round(
                (1 - len(processed_content) / len(content)) * 100, 2
            ) if content else 0

            logger.debug(f"Content preprocessed: {metadata['original_length']} -> "
                        f"{metadata['processed_length']} chars "
                        f"({metadata['reduction_percent']}% reduction)")

            return processed_content, metadata

        except Exception as e:
            logger.error(f"Error in content preprocessing pipeline: {e}")
            return content, metadata

    def process_for_embedding(self, content: str, content_type: str = "html") -> str:
        """
        Simplified method that returns only the processed content.
        Use this when you don't need the metadata.

        Args:
            content: Raw content (HTML or Markdown)
            content_type: "html" or "markdown"

        Returns:
            Processed content ready for embedding
        """
        processed_content, _ = self.process(content, content_type)
        return processed_content
