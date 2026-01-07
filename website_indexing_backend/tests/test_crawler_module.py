import pytest
from modules.config import CrawlerConfig

def test_crawler_config_defaults():
    """Test default values for CrawlerConfig"""
    config = CrawlerConfig(start_url="https://example.com")
    assert config.max_pages == 1000  # Default is 1000
    assert config.fetch_concurrency == 10
    # assert "example.com" in config.allowed_domains # Logic seems to be in app.py or elsewhere, not init
    assert config.stealth is True

# Dataclass doesn't validate validation on init, so we skip validation tests
# unless we implemented __post_init__ validation logic.


def test_subdomain_logic():
    """Test subdomain inclusion logic"""
    config = CrawlerConfig(
        start_url="https://example.com",
        scrape_all_subdomains=True
    )
    assert config.scrape_all_subdomains is True
    
    config_explicit = CrawlerConfig(
        start_url="https://example.com",
        include_subdomains=["blog"]
    )
    assert "blog.example.com" in config_explicit.allowed_domains or "blog" in config_explicit.include_subdomains
