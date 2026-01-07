"""
Configuration management for the website indexing pipeline.
Handles all configuration loading, validation, and environment variable processing.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class CrawlerConfig:
    """Crawler-specific configuration."""
    start_url: str = ""
    max_pages: int = 1000
    fetch_concurrency: int = 10
    download_concurrency: int = 20
    timeout: int = 30
    output_dir: str = "data/raw"
    state_file: str = "crawl_state.json"
    mapping_file: str = "mappings.json"
    allowed_domains: List[str] = field(default_factory=list)
    excluded_subdomains: List[str] = field(default_factory=list)
    excluded_patterns: List[Dict[str, str]] = field(default_factory=list)  # List of {pattern: str, type: str}
    stealth: bool = True
    headless: bool = True
    default_delay: float = 1.0
    max_file_size_mb: int = 500
    dynamic_scroll_count: int = 5
    dynamic_scroll_delay: int = 1
    dynamic_click_selectors: List[str] = field(default_factory=list)
    dynamic_action_delay: int = 5
    autosave_interval_sec: int = 60
    auto_restart: bool = False
    max_restarts: int = 3
    restart_backoff_sec: int = 5
    magic: bool = True  # Bug #14 fix: Enable JavaScript rendering by default
    wait_for: str = ""
    css_selector: str = ""
    remove_overlay_elements: bool = False  # Bug fix: Default to False to prevent navbar removal
    # Advanced dynamic content handling (Bug #14 fix: Enable by default)
    infinite_scroll_enabled: bool = True  # Enable infinite scroll handling
    infinite_scroll_max_scrolls: int = 20
    shadow_dom_traversal: bool = True  # Enable Shadow DOM traversal
    lazy_load_images: bool = True
    scroll_stability_checks: int = 3
    scroll_wait_time: float = 1.0  # Wait time between scroll operations
    dynamic_content_wait: float = 5.0  # Timeout for dynamic content loading
    # Link extraction enhancement - ensures all links are discovered
    scan_full_page: bool = True  # Enable full page scanning for better link extraction
    delay_before_return_html: float = 3.0  # Seconds to wait after page load before extracting links
    # Subdomain discovery
    scrape_all_subdomains: bool = False
    include_subdomains: List[str] = field(default_factory=list)
    # P2: Site identification for exclusion filtering
    site_id: str = ""  # UUID of the site for exclusion pattern lookup



@dataclass
class ProcessingConfig:
    """Document processing configuration."""
    html_workers: int = 8
    pdf_concurrency: int = 8
    pdf_enabled: bool = True
    chunking_enabled: bool = True
    summaries_enabled: bool = False
    summary_model: str = "llama-3.3-70b-versatile"
    max_batch_size: int = 25
    retry_attempts: int = 3
    retry_delay: int = 5
    batch_delay: int = 1
    max_tokens: int = 32000
    temperature: float = 0.1
    chunk_size: int = 50000

    def __post_init__(self):
        import os
        if os.getenv("SUMMARY_MODEL"):
            self.summary_model = os.getenv("SUMMARY_MODEL")


@dataclass
class PreprocessorConfig:
    """Content preprocessing configuration."""
    # All enabled by default per user decision
    enable_script_style_removal: bool = True
    enable_media_tokenizer: bool = True
    enable_url_tokenizer: bool = True
    enable_boilerplate_removal: bool = True
    enable_gibberish_detection: bool = True  # Bug #22 fix: Enable gibberish detection
    custom_boilerplate_selectors: List[str] = field(default_factory=list)
    preserve_alt_text: bool = True  # Keep image alt text as context
    gibberish_quality_threshold: int = 30  # Content below this score is flagged


@dataclass
class DynamicContentConfig:
    """Dynamic content handling configuration."""
    infinite_scroll_enabled: bool = True  # Bug #14 fix: Enable by default
    infinite_scroll_max_scrolls: int = 20
    shadow_dom_traversal: bool = True  # Enable Shadow DOM traversal
    lazy_load_images: bool = True
    scroll_stability_checks: int = 3
    scroll_wait_time: float = 1.0
    dynamic_content_wait: float = 5.0  # Timeout for dynamic content loading
    expand_collapsed_content: bool = True  # Expand accordions and details


@dataclass
class PDFConfig:
    """PDF processing configuration."""
    # Processing options
    enabled: bool = True
    ocr_enabled: bool = False  # DEPRECATED: auto_ocr is now default in processor
    max_pages: int = 100
    extract_images: bool = True

    # Download options (for in-memory processing)
    max_size_mb: int = 20  # Maximum PDF size in MB (reduced for memory efficiency)
    download_timeout: int = 120  # Download timeout in seconds
    max_retries: int = 3  # Number of retry attempts
    streaming_threshold_mb: int = 10  # Use streaming for files larger than this

    # OCR cost optimization settings
    max_images_per_page: int = 5  # Limit images OCR'd per page (cost control)
    max_images_per_pdf: int = 20  # Limit total images OCR'd per PDF (cost control)
    min_image_size: int = 100  # Minimum image dimension to OCR (skip icons/bullets)
    prioritize_large_images: bool = True  # OCR larger images first (more likely charts)
    ocr_timeout_per_image: int = 30  # Timeout per image OCR call

    def __post_init__(self):
        """Load configuration from environment variables."""
        import os
        if os.getenv("MAX_PDF_SIZE_MB"):
            self.max_size_mb = int(os.getenv("MAX_PDF_SIZE_MB"))
        if os.getenv("PDF_DOWNLOAD_TIMEOUT"):
            self.download_timeout = int(os.getenv("PDF_DOWNLOAD_TIMEOUT"))
        if os.getenv("PDF_MAX_RETRIES"):
            self.max_retries = int(os.getenv("PDF_MAX_RETRIES"))
        if os.getenv("PDF_OCR_ENABLED"):
            self.ocr_enabled = os.getenv("PDF_OCR_ENABLED", "false").lower() == "true"
        if os.getenv("PDF_MAX_IMAGES_PER_PAGE"):
            self.max_images_per_page = int(os.getenv("PDF_MAX_IMAGES_PER_PAGE"))
        if os.getenv("PDF_MAX_IMAGES_PER_PDF"):
            self.max_images_per_pdf = int(os.getenv("PDF_MAX_IMAGES_PER_PDF"))
        if os.getenv("PDF_MIN_IMAGE_SIZE"):
            self.min_image_size = int(os.getenv("PDF_MIN_IMAGE_SIZE"))


@dataclass
class SubdomainConfig:
    """Subdomain discovery configuration."""
    scrape_all_subdomains: bool = False
    include_subdomains: List[str] = field(default_factory=list)
    # DNS enumeration not implemented per user decision


@dataclass
class EmbeddingConfig:
    """Embedding and indexing configuration."""
    pinecone_index: str = "webbotify-index-3072"  # Using 3072-dimension index for Gemini embeddings
    embed_model: str = "gemini-embedding-001"  # Use Gemini embeddings
    include_full_content: bool = False
    include_summary: bool = True
    final_combined_json: str = "data/Final_combined_data.json"
    formatted_output: str = "data/embeddings/summary_only_documents.json"
    # Namespace configuration
    use_namespaces: bool = True
    namespace_prefix: str = "website_domain"
    # Optional direct namespace override for multi-tenant routing
    namespace_override: str | None = None
    chunk_size: int = 1000
    chunk_overlap: int = 200
    # Gemini API configuration
    gemini_api_key: str = ""
    gemini_embedding_dimensions: int = 3072  # Gemini default (supports 768, 1536, 3072)
    
    def __post_init__(self):
        """Load configuration from environment variables."""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        # Override with environment variables if they exist
        if os.getenv("PINECONE_INDEX"):
            self.pinecone_index = os.getenv("PINECONE_INDEX")
        if os.getenv("EMBED_MODEL"):
            self.embed_model = os.getenv("EMBED_MODEL")
        if os.getenv("USE_NAMESPACES"):
            self.use_namespaces = os.getenv("USE_NAMESPACES").lower() == "true"
        if os.getenv("NAMESPACE_PREFIX"):
            self.namespace_prefix = os.getenv("NAMESPACE_PREFIX")
        if os.getenv("NAMESPACE_OVERRIDE"):
            self.namespace_override = os.getenv("NAMESPACE_OVERRIDE")
        if os.getenv("GEMINI_API_KEY"):
            self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        if os.getenv("GEMINI_EMBEDDING_DIMENSIONS"):
            self.gemini_embedding_dimensions = int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS"))


@dataclass
class ServerConfig:
    """Server and global application configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    data_dir: str = "data"

    def __post_init__(self):
        """Load configuration from environment variables."""
        import os
        import json
        
        if os.getenv("HOST"):
            self.host = os.getenv("HOST")
        if os.getenv("API_PORT"):
            self.port = int(os.getenv("API_PORT"))
            
        origins = os.getenv("CORS_ALLOWED_ORIGINS")
        if origins:
            try:
                self.cors_origins = json.loads(origins)
            except json.JSONDecodeError:
                # Fallback for comma-separated string
                self.cors_origins = [o.strip() for o in origins.split(",")]
        
        if os.getenv("DATA_DIR"):
            self.data_dir = os.getenv("DATA_DIR")


@dataclass
class PipelineConfig:
    """Main pipeline configuration."""
    run_name: str = "default"
    stages: List[str] = field(default_factory=lambda: ["stream_index"])
    resume: bool = True
    force_stages: List[str] = field(default_factory=list)
    
    # API Keys and external service URLs
    pinecone_api_key: str = ""
    django_backend_url: str = "http://localhost:8001"
    
    # Sub-configurations
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    server: ServerConfig = field(default_factory=ServerConfig)  # Add server config
    
    # Paths
    paths: Dict[str, str] = field(default_factory=lambda: {
        "root": ".",
        "output_data": os.path.join(os.getenv("DATA_DIR", "data"), "raw"),
        "output_data_clean": os.path.join(os.getenv("DATA_DIR", "data"), "clean"),
        "output_data_md": os.path.join(os.getenv("DATA_DIR", "data"), "html_md"),
        "pdf_input_dir": os.path.join(os.getenv("DATA_DIR", "data"), "raw"),
        "pdf_md_dir": os.path.join(os.getenv("DATA_DIR", "data"), "pdf_md"),
        "pdf_pages_dir": os.path.join(os.getenv("DATA_DIR", "data"), "pdf_pages"),
        "mappings_dir": os.path.join(os.getenv("DATA_DIR", "data"), "mappings"),
        "combined_md_dir": os.path.join(os.getenv("DATA_DIR", "data"), "combined_md_files"), # Maybe this should be inside data too? Keeping as is based on existing, but maybe move it? Existing was "combined_md_files" at root likely. Let's move it to data/combined for consistency if possible, or keep it strict. Existing config had "combined_md_files". I'll put it in data/combined_md_files for better organization.
        "summaries_dir": os.path.join(os.getenv("DATA_DIR", "data"), "summaries"),
        "embeddings_dir": os.path.join(os.getenv("DATA_DIR", "data"), "embeddings")
    })
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "data/pipeline.log"

    @classmethod
    def load_from_yaml(cls, config_path: str) -> "PipelineConfig":
        """Load configuration from YAML file."""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        pipeline_data = data.get("pipeline", {})
        crawler_data = data.get("crawler", {})
        processing_data = data.get("processing", {})
        embedding_data = data.get("embedding", {})
        
        # Create crawler config
        crawler_config = CrawlerConfig(
            start_url=crawler_data.get("start_url", ""),
            max_pages=crawler_data.get("max_pages", 1000),
            fetch_concurrency=crawler_data.get("fetch_concurrency", 10),
            download_concurrency=crawler_data.get("download_concurrency", 20),
            timeout=crawler_data.get("timeout", 30),
            output_dir=crawler_data.get("output_dir", "data/raw"),
            state_file=crawler_data.get("state_file", "crawl_state.json"),
            mapping_file=crawler_data.get("mapping_file", "mappings.json"),
            allowed_domains=crawler_data.get("allowed_domains", []),
            excluded_subdomains=crawler_data.get("excluded_subdomains", []),
            stealth=crawler_data.get("stealth", True),
            headless=crawler_data.get("headless", True),
            default_delay=crawler_data.get("default_delay", 1.0),
            max_file_size_mb=crawler_data.get("max_file_size_mb", 500),
            dynamic_scroll_count=crawler_data.get("dynamic_scroll_count", 5),
            dynamic_scroll_delay=crawler_data.get("dynamic_scroll_delay", 1),
            dynamic_click_selectors=crawler_data.get("dynamic_click_selectors", []),
            dynamic_action_delay=crawler_data.get("dynamic_action_delay", 5),
            autosave_interval_sec=crawler_data.get("autosave_interval_sec", 60),
            auto_restart=crawler_data.get("auto_restart", False),
            max_restarts=crawler_data.get("max_restarts", 3),

            restart_backoff_sec=crawler_data.get("restart_backoff_sec", 5),
            remove_overlay_elements=crawler_data.get("remove_overlay_elements", False)
        )
        
        # Override crawler config with environment variables
        if os.getenv("CRAWLER_REMOVE_OVERLAYS"):
            crawler_config.remove_overlay_elements = os.getenv("CRAWLER_REMOVE_OVERLAYS").lower() == "true"
        
        # Create processing config
        processing_config = ProcessingConfig(
            html_workers=processing_data.get("html_workers", 8),
            pdf_concurrency=processing_data.get("pdf_concurrency", 8),
            pdf_enabled=processing_data.get("pdf_enabled", True),
            chunking_enabled=processing_data.get("chunking_enabled", True),
            summaries_enabled=processing_data.get("summaries_enabled", False),
            summary_model=processing_data.get("summary_model", "llama-3.3-70b-versatile"),
            max_batch_size=processing_data.get("max_batch_size", 25),
            retry_attempts=processing_data.get("retry_attempts", 3),
            retry_delay=processing_data.get("retry_delay", 5),
            batch_delay=processing_data.get("batch_delay", 1),
            max_tokens=processing_data.get("max_tokens", 32000),
            temperature=processing_data.get("temperature", 0.1),
            chunk_size=processing_data.get("chunk_size", 50000)
        )

        # Override processing config with environment variables
        if os.getenv("SUMMARY_MODEL"):
            processing_config.summary_model = os.getenv("SUMMARY_MODEL")
            
        # Create embedding config
        embedding_config = EmbeddingConfig(
            pinecone_index=embedding_data.get("pinecone_index", "webbotify-index-3072"),
            embed_model=embedding_data.get("embed_model", "gemini-embedding-001"),
            include_full_content=embedding_data.get("include_full_content", False),
            include_summary=embedding_data.get("include_summary", True),
            final_combined_json=embedding_data.get("final_combined_json", "data/Final_combined_data.json"),
            formatted_output=embedding_data.get("formatted_output", "data/embeddings/summary_only_documents.json")
        )
        
        return cls(
            run_name=pipeline_data.get("run_name", "default"),
            stages=pipeline_data.get("stages", ["stream_index"]),
            resume=pipeline_data.get("resume", True),
            force_stages=pipeline_data.get("force_stages", []),
            crawler=crawler_config,
            processing=processing_config,
            embedding=embedding_config,
            paths=data.get("paths", {}),
            log_level=data.get("logging", {}).get("level", "INFO"),
            log_file=data.get("logging", {}).get("file", "data/pipeline.log")
        )

    def get_path(self, key: str, project_root: str = ".") -> str:
        """Get absolute path for a given key."""
        return str(Path(project_root) / self.paths.get(key, key))

    def ensure_directories(self, project_root: str = ".") -> None:
        """Ensure all required directories exist."""
        for path_key in self.paths:
            path = self.get_path(path_key, project_root)
            Path(path).mkdir(parents=True, exist_ok=True)


def get_config() -> PipelineConfig:
    """
    Get the default pipeline configuration.
    Loads from environment variables and returns a PipelineConfig instance.
    """
    # Load environment variables
    load_dotenv()
    
    # Create a basic config with environment variable overrides
    config = PipelineConfig()
    
    # Override with environment variables
    if os.getenv("PINECONE_API_KEY"):
        config.embedding.pinecone_api_key = os.getenv("PINECONE_API_KEY")
    if os.getenv("PINECONE_INDEX"):
        config.embedding.pinecone_index = os.getenv("PINECONE_INDEX")
    if os.getenv("EMBED_MODEL"):
        config.embedding.embed_model = os.getenv("EMBED_MODEL")
    if os.getenv("DJANGO_BACKEND_URL"):
        config.django_backend_url = os.getenv("DJANGO_BACKEND_URL")
    
    return config
