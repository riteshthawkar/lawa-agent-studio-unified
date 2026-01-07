# Production Dockerfile for Website Indexing API
# Pre-installs Playwright browsers to avoid download during deployment
# NOTE: Must be built with context at project root (../) to include backend/ dependency

FROM python:3.11-slim

# Install system dependencies required for Playwright Chromium
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Create base app directory
WORKDIR /app

# Copy requirements first for better caching
COPY website_indexing_backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (pre-installed in image)
# This runs ONCE during image build, not during deployment
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application code
# We copy both the service code and the backend dependency
COPY website_indexing_backend/ website_indexing_backend/
COPY backend/ backend/
# Create logs directory for the shared backend code (required by Django settings)
RUN mkdir -p backend/logs && chmod 777 backend/logs

# Switch to service directory for runtime
WORKDIR /app/website_indexing_backend

# Create data directories (inside the service dir)
RUN mkdir -p data/raw data/clean data/html_md data/pdf_md data/pdf_pages \
    data/mappings combined_md_files data/summaries data/embeddings

# Expose API port
EXPOSE 8080

# Health check (path is relative to WORKDIR)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Run the API server
# Use 4 workers for production (adjust based on CPU cores)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4", "--no-access-log"]
