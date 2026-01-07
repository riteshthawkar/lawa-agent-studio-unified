#!/usr/bin/env python3
"""
Startup script for the Website Indexing FastAPI application.
Handles environment setup and starts the server.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
import uvicorn
from modules.config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_environment():
    """Check if required environment variables are set."""
    required_vars = ["PINECONE_API_KEY", "GEMINI_API_KEY"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.warning("Please set these in your .env file or environment")
        return False
    
    logger.info("✅ All required environment variables are set")
    return True


def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import fastapi
        import uvicorn
        import aiohttp
        import playwright
        logger.info("✅ Core dependencies are available")
        return True
    except ImportError as e:
        logger.error(f"❌ Missing dependency: {e}")
        logger.error("Please run: pip install -r requirements_clean.txt")
        return False


def ensure_directories():
    """Ensure required directories exist."""
    config = get_config()
    config.ensure_directories()
    logger.info("✅ Required directories created")


def start_server(host: str = "0.0.0.0", port: int = 8080, reload: bool = True):
    """Start the FastAPI server."""
    logger.info(f"🚀 Starting Website Indexing API on {host}:{port}")
    logger.info(f"📖 API Documentation: http://{host}:{port}/docs")
    logger.info(f"🔄 Auto-reload: {'enabled' if reload else 'disabled'}")
    
    try:
        uvicorn.run(
            "app:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Server error: {e}")
        sys.exit(1)


def main():
    """Main startup function."""
    import argparse
    
    config = get_config()
    
    parser = argparse.ArgumentParser(description="Start Website Indexing API")
    parser.add_argument("--host", default=config.server.host, help="Host to bind to")
    parser.add_argument("--port", type=int, default=config.server.port, help="Port to bind to")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    parser.add_argument("--skip-checks", action="store_true", help="Skip environment checks")
    
    args = parser.parse_args()
    
    print("🚀 Website Indexing API Startup")
    print("=" * 50)
    
    if not args.skip_checks:
        # Check dependencies
        if not check_dependencies():
            sys.exit(1)
        
        # Check environment
        check_environment()
        
        # Ensure directories
        ensure_directories()
    
    # Start server
    start_server(
        host=args.host,
        port=args.port,
        reload=not args.no_reload
    )


if __name__ == "__main__":
    main()
