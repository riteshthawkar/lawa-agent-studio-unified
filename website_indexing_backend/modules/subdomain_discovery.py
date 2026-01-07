"""
Subdomain discovery module for web crawling.
Discovers subdomains from crawled links (no DNS enumeration per user decision).
"""

import logging
from typing import Set, List, Optional, Dict, Any
from urllib.parse import urlparse
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SubdomainConfig:
    """Configuration for subdomain discovery."""
    scrape_all_subdomains: bool = False
    include_subdomains: List[str] = field(default_factory=list)
    # DNS enumeration NOT implemented per user decision
    # Only link-based discovery is used


class SubdomainDiscovery:
    """
    Discover and manage subdomains during crawling.
    Uses link-based discovery only (no DNS enumeration).
    """

    def __init__(self, base_domain: str, config: SubdomainConfig = None):
        """
        Initialize subdomain discovery.

        Args:
            base_domain: The primary domain to discover subdomains for (e.g., 'example.com')
            config: Configuration for subdomain discovery
        """
        self.base_domain = self._normalize_domain(base_domain)
        self.config = config or SubdomainConfig()

        # Set of discovered subdomains (e.g., {'www', 'blog', 'docs'})
        self.discovered: Set[str] = set()

        # Set of full subdomain domains (e.g., {'www.example.com', 'blog.example.com'})
        self.discovered_domains: Set[str] = set()

        # Always include explicitly specified subdomains
        for subdomain in self.config.include_subdomains:
            self._add_subdomain(subdomain)

        # Statistics
        self.stats = {
            "urls_analyzed": 0,
            "subdomains_discovered": 0,
            "subdomains_from_links": 0
        }

        logger.info(f"SubdomainDiscovery initialized for {self.base_domain} "
                   f"(scrape_all={self.config.scrape_all_subdomains}, "
                   f"explicit_subdomains={self.config.include_subdomains})")

    def _normalize_domain(self, domain: str) -> str:
        """Normalize a domain by removing protocol, www prefix, and trailing slashes."""
        # If it looks like a URL, parse it
        if '://' in domain:
            parsed = urlparse(domain)
            domain = parsed.netloc

        # Remove www prefix for base domain matching
        if domain.startswith('www.'):
            domain = domain[4:]

        return domain.lower().strip().rstrip('/')

    def _add_subdomain(self, subdomain: str):
        """Add a subdomain to the discovered set."""
        subdomain = subdomain.lower().strip()
        if subdomain and subdomain != 'www':
            self.discovered.add(subdomain)
            full_domain = f"{subdomain}.{self.base_domain}"
            self.discovered_domains.add(full_domain)
            self.stats["subdomains_discovered"] = len(self.discovered)

    def extract_subdomain(self, url: str) -> Optional[str]:
        """
        Extract subdomain from URL if it belongs to the base domain.

        Args:
            url: The URL to analyze

        Returns:
            The subdomain part (e.g., 'blog' from 'blog.example.com'),
            None if the URL doesn't belong to the base domain or has no subdomain
        """
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()

            if not host:
                return None

            # Check if this host belongs to our base domain
            if host == self.base_domain:
                return None  # No subdomain (root domain)

            if host.endswith('.' + self.base_domain):
                # Extract the subdomain part
                subdomain_part = host[:-len('.' + self.base_domain)]

                # Handle nested subdomains (e.g., 'api.v2.example.com' -> 'api.v2')
                if subdomain_part and subdomain_part != 'www':
                    return subdomain_part

            return None

        except Exception as e:
            logger.debug(f"Error extracting subdomain from {url}: {e}")
            return None

    def discover_from_links(self, links: List[str]) -> Set[str]:
        """
        Discover subdomains from a list of crawled links.

        Args:
            links: List of URLs found during crawling

        Returns:
            Set of newly discovered subdomains
        """
        new_discoveries = set()

        for link in links:
            self.stats["urls_analyzed"] += 1

            subdomain = self.extract_subdomain(link)
            if subdomain and subdomain not in self.discovered:
                self._add_subdomain(subdomain)
                new_discoveries.add(subdomain)
                self.stats["subdomains_from_links"] += 1
                logger.info(f"Discovered new subdomain from link: {subdomain}.{self.base_domain}")

        return new_discoveries

    def discover_from_url(self, url: str) -> Optional[str]:
        """
        Check a single URL for subdomain discovery.

        Args:
            url: The URL to check

        Returns:
            The subdomain if newly discovered, None otherwise
        """
        self.stats["urls_analyzed"] += 1

        subdomain = self.extract_subdomain(url)
        if subdomain and subdomain not in self.discovered:
            self._add_subdomain(subdomain)
            self.stats["subdomains_from_links"] += 1
            logger.info(f"Discovered new subdomain: {subdomain}.{self.base_domain}")
            return subdomain

        return None

    def build_allowed_domains(self, include_base: bool = True) -> List[str]:
        """
        Build a list of allowed domains including discovered subdomains.

        Args:
            include_base: Whether to include the base domain

        Returns:
            List of domain strings suitable for crawler's allowed_domains
        """
        domains = []

        if include_base:
            domains.append(self.base_domain)
            # Also include www subdomain
            domains.append(f"www.{self.base_domain}")

        # Add all discovered subdomain domains
        domains.extend(sorted(self.discovered_domains))

        return domains

    def should_follow_subdomain(self, url: str) -> bool:
        """
        Check if a URL's subdomain should be followed based on configuration.

        Args:
            url: The URL to check

        Returns:
            True if the URL should be followed, False otherwise
        """
        subdomain = self.extract_subdomain(url)

        # Root domain is always allowed
        if subdomain is None:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            # Check if it's the base domain or www
            if host == self.base_domain or host == f"www.{self.base_domain}":
                return True
            return False

        # If scrape_all_subdomains is enabled, allow any subdomain
        if self.config.scrape_all_subdomains:
            return True

        # Check if subdomain is in the explicit include list
        if subdomain in self.config.include_subdomains:
            return True

        # Check if subdomain was already discovered (and thus allowed)
        if subdomain in self.discovered:
            return True

        return False

    def get_discovered_subdomains(self) -> List[str]:
        """Get list of discovered subdomains."""
        return sorted(list(self.discovered))

    def get_discovered_domains(self) -> List[str]:
        """Get list of full discovered subdomain domains."""
        return sorted(list(self.discovered_domains))

    def get_stats(self) -> Dict[str, Any]:
        """Get discovery statistics."""
        return {
            **self.stats,
            "base_domain": self.base_domain,
            "discovered_subdomains": self.get_discovered_subdomains(),
            "total_allowed_domains": len(self.build_allowed_domains())
        }

    def merge_with_existing(self, existing_allowed_domains: List[str]) -> List[str]:
        """
        Merge discovered subdomains with an existing allowed domains list.

        Args:
            existing_allowed_domains: Existing list of allowed domains

        Returns:
            Combined list with no duplicates
        """
        combined = set(existing_allowed_domains or [])
        combined.update(self.build_allowed_domains())
        return sorted(list(combined))

    def is_same_site(self, url: str) -> bool:
        """
        Check if a URL belongs to the same site (base domain + any subdomain).

        Args:
            url: The URL to check

        Returns:
            True if the URL is part of the same site
        """
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()

            if not host:
                return False

            # Exact match with base domain
            if host == self.base_domain:
                return True

            # Check if it's a subdomain of base domain
            if host.endswith('.' + self.base_domain):
                return True

            return False

        except Exception:
            return False
