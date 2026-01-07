# Website Indexing API

A FastAPI-based web service for scraping, processing, and indexing website content into Pinecone vector database with hybrid search capabilities (dense + sparse vectors) and namespace support.

> Detailed, production-ready API reference is available in `API_SPEC.md`.

## 🚀 Features

- **Two-Phase Processing**: Collect URLs first, then process iteratively
- **Hybrid Search**: Dense vectors (semantic) + Sparse vectors (keyword) for optimal search
- **Pinecone Namespaces**: Organize data by website domain
- **Memory-Only Processing**: No temporary files created during processing
- **Concurrent Processing**: Handle multiple indexing tasks simultaneously
- **REST API**: Easy integration with other applications
- **PostgreSQL Database**: Persistent task storage and management
- **Official Pinecone Text Library**: Professional-grade BM25 sparse embeddings
- **Advanced Web Scraping**: JavaScript rendering, rate limiting, retry logic

## 🏗️ Complete Pipeline Architecture

### **Phase 1: URL Collection**
- **Component**: `URLCollector` (`modules/url_collector.py`)
- **Process**: 
  - Launches headless Playwright browser
  - Navigates to starting URL and extracts all links using JavaScript
  - Validates URLs (domain restrictions, file type exclusions, robots.txt compliance)
  - Collects up to `max_pages` limit
  - Tracks collection statistics

### **Phase 2: Iterative Processing**
- **Component**: `IterativeProcessor` (`modules/iterative_processor.py`)
- **Process**:
  - Fetches content from each collected URL using Playwright
  - Converts HTML to clean Markdown using `markitdown` library
  - Generates hybrid embeddings (dense + sparse vectors)
  - Indexes to Pinecone with domain-based namespaces

### **Hybrid Embedding System**
- **Component**: `DocumentEmbedder` (`modules/embedder.py`)
- **Dense Vectors**: `Qwen/Qwen3-Embedding-0.6B` (1024 dimensions) for semantic search
- **Sparse Vectors**: `BM25Encoder.default()` from Pinecone Text library for keyword search
- **Vector Structure**:
  ```json
  {
    "id": "html_fa5a245f6b6f",
    "values": [0.1234, -0.5678, ...],  // 1024-dimensional dense vector
    "sparse_values": {
      "indices": [3368723024, 1793137844, ...],  // BM25 indices
      "values": [0.5434, 0.5434, ...]           // BM25 values
    },
    "metadata": {
      "source": "https://verifylabs.ai/",
      "context": "Full webpage content in Markdown..."
    }
  }
  ```

## 📄 PDF Processing Capabilities

**Current Status**: PDF processing is **available but not integrated** into the main pipeline.

### **PDF Processor Component**
- **File**: `modules/pdf_processor.py`
- **Capabilities**:
  - **PDF Text Extraction**: Using PyMuPDF (fitz)
  - **OCR Support**: Gemini AI for image-based PDFs
  - **Embedded Images**: Extracts and processes embedded graphics
  - **Markdown Conversion**: Converts PDF content to structured Markdown
  - **Multi-format Support**: PDFs, Word docs, Excel files

### **PDF Processing Features**:
1. **Page-by-page Processing**: Converts each PDF page to images
2. **OCR Integration**: Uses Gemini AI for text extraction from images
3. **Embedded Graphics**: Processes charts, diagrams, and embedded images
4. **Metadata Extraction**: Title, author, creation date
5. **Clean Markdown Output**: Structured, readable content

### **To Enable PDF Processing**:
Currently, PDF files are **excluded** from URL collection. To enable PDF processing:

1. **Remove PDF exclusion** in `modules/url_collector.py`:
   ```python
   # Remove '.pdf' from skip_extensions
   skip_extensions = {'.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', ...}
   ```

2. **Integrate PDF processor** in `modules/iterative_processor.py`:
   ```python
   from .pdf_processor import PDFProcessor
   
   # Add PDF detection and processing logic
   if url.endswith('.pdf'):
       # Process PDF using PDFProcessor
   ```

3. **Add file download capability** for PDF URLs

## 🛠️ Quick Start

### 1. Setup Environment

```bash
# Create virtual environment
python -m venv env

# Activate environment
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configure Environment

```bash
# Edit .env with your API keys
nano .env
```

**Required environment variables:**
```bash
# Pinecone Configuration
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX=lawa-website-index
EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B
USE_NAMESPACES=true
NAMESPACE_PREFIX=website_domain

# PostgreSQL Database Configuration
LAWA_DB_PG_HOST=databae_url
LAWA_DB_PG_PORT=port
LAWA_DB_PG_USER=user
LAWA_DB_PG_PASSWORD=your_actual_password
LAWA_DB_PG_DATABASE=database_name

# Optional for OCR
GEMINI_API_KEY=your_gemini_api_key
```

### 3. Setup Database

```bash
# Run database migration to create tables
python migrate_database.py
```

### 4. Start the API

```bash
# Start the server
python start_api.py

# Optional: disable sparse or tune timeouts if BM25 is slow on your env
# DISABLE_SPARSE=true BM25_INIT_TIMEOUT_SEC=10 BM25_MIN_DOCS=5 python start_api.py
```

The API will be available at: http://localhost:8000

## 📡 API Usage

### Index a Website (Multi-tenant ready)

```bash
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_pages": 50,
    "tenant_id": "tenant_123",
    "site_id": "site_456",
    "external_job_id": "job-abc-123",   
    "callback_url": "https://platform.example.com/webhooks/indexing",
    "use_namespaces": true,
    "namespace_prefix": "website_domain",
    "pinecone_index": "lawa-website-index"
  }'
```

### Check Task Status

```bash
# Get all tasks
curl http://localhost:8000/tasks

# Get specific task
curl http://localhost:8000/tasks/{task_id}
```

### Health Check

```bash
curl http://localhost:8000/health
```

## 📊 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index` | POST | Start indexing task (supports tenant_id, site_id, external_job_id, callback_url) |
| `/tasks` | GET | List tasks; filters: tenant_id, site_id, external_job_id, status, limit |
| `/tasks/{task_id}` | GET | Get task status |
| `/tasks/{task_id}` | DELETE | Cancel task |
| `/health` | GET | Health check |
| `/stats` | GET | System statistics |

## 🏗️ Project Structure

```
├── app.py                           # FastAPI application
├── start_api.py                     # Application startup script
├── modules/                         # Core processing modules
│   ├── config.py                   # Configuration classes
│   ├── crawler.py                  # Web crawling logic
│   ├── embedder.py                 # Hybrid embedding (dense + sparse)
│   ├── html_processor.py           # HTML to Markdown conversion
│   ├── pdf_processor.py            # PDF processing with OCR
│   ├── iterative_processor.py      # Individual URL processing
│   ├── two_phase_processor.py      # Main orchestration
│   └── url_collector.py            # URL collection logic
├── configs/                         # Configuration files
├── data/                           # Data directories (auto-created)
└── env/                            # Virtual environment
```

## 🔍 Hybrid Search Capabilities

### **Dense Vectors (Semantic Search)**
- **Model**: `Qwen/Qwen3-Embedding-0.6B`
- **Dimensions**: 1024
- **Purpose**: Find documents by meaning and context
- **Library**: Sentence Transformers

### **Sparse Vectors (Keyword Search)**
- **Model**: `BM25Encoder.default()` from Pinecone Text
- **Purpose**: Find documents by exact keywords
- **Library**: `pinecone-text>=0.11.0`
- **Parameters**: Pre-trained on MS MARCO dataset

### **Combined Benefits**
- **Semantic Understanding**: Find relevant content even with different wording
- **Exact Matching**: Find specific terms and phrases
- **Comprehensive Results**: Best of both search approaches

## 🌐 Namespace Support

Each website is indexed into its own Pinecone namespace:
- `website_domain_example_com` for example.com
- `website_domain_verifylabs_ai` for verifylabs.ai

This provides:
- **Data Isolation**: Separate different websites
- **Efficient Querying**: Search within specific domains
- **Scalable Organization**: Easy management of multiple sites

## 🗄️ PostgreSQL Database Integration

### **Persistent Task Storage**
- **Component**: `DatabaseManager` (`modules/database.py`)
- **Features**:
  - **Task Persistence**: All tasks stored in PostgreSQL
  - **Status Tracking**: Real-time task status updates
  - **Result Storage**: Complete task results and metadata
  - **Error Handling**: Detailed error logging and recovery
  - **Statistics**: Comprehensive task analytics

### **Database Schema**
```sql
CREATE TABLE indexing_tasks (
    task_id VARCHAR(36) PRIMARY KEY,
    url TEXT NOT NULL,
    max_pages INTEGER DEFAULT 100,
    allowed_domains JSON,
    excluded_subdomains JSON,
    pinecone_index VARCHAR(255),
    embed_model VARCHAR(255),
    streaming_mode BOOLEAN DEFAULT TRUE,
    use_namespaces BOOLEAN DEFAULT TRUE,
    namespace_prefix VARCHAR(255) DEFAULT 'website_domain',
    custom_config JSON,
    status VARCHAR(50) DEFAULT 'queued',
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    phase1_result JSON,
    phase2_result JSON,
    error_message TEXT,
    urls_collected INTEGER DEFAULT 0,
    urls_processed INTEGER DEFAULT 0,
    documents_indexed INTEGER DEFAULT 0
);
```

### **Database Benefits**
- **Reliability**: Tasks survive server restarts
- **Scalability**: Handle thousands of concurrent tasks
- **Monitoring**: Complete task history and analytics
- **Recovery**: Resume interrupted tasks
- **Auditing**: Full task lifecycle tracking

## ⚙️ Configuration Options

### **CrawlerConfig**
- `max_pages`: Maximum URLs to collect (default: 100)
- `timeout`: Request timeout in seconds (default: 30)
- `user_agent`: Browser user agent string
- `allowed_domains`: Restrict crawling to specific domains

### **EmbeddingConfig**
- `pinecone_index`: Target Pinecone index name
- `embed_model`: Dense embedding model
- `use_namespaces`: Enable namespace separation
- `namespace_prefix`: Namespace naming pattern

## 🔄 Complete Process Flow

1. **API Request**: User sends POST to `/index` with URL
2. **Task Creation**: Background task queued with unique ID
3. **Phase 1 - URL Collection**:
   - Initialize Playwright browser
   - Navigate to starting URL
   - Extract all links using JavaScript
   - Validate and filter URLs
   - Collect up to `max_pages` limit
4. **Phase 2 - Content Processing**:
   - For each collected URL:
     - Fetch HTML content
     - Convert to Markdown
     - Generate dense embedding (Qwen)
     - Generate sparse embedding (BM25)
     - Create hybrid vector
     - Index to Pinecone with namespace
5. **Task Completion**: Update status and return results

## 📈 Performance Features

- **Memory Efficient**: No temporary files, all in-memory processing
- **Concurrent Processing**: Multiple tasks can run simultaneously
- **Batch Operations**: Efficient Pinecone indexing (100 vectors per batch)
- **Rate Limiting**: Respectful web scraping with delays
- **Retry Logic**: Robust error handling with exponential backoff
- **Progress Tracking**: Real-time task status updates

## 🛡️ Robustness Features

- **Error Handling**: Comprehensive retry logic and error recovery
- **Validation**: URL and content validation at multiple stages
- **Rate Limiting**: Respectful web scraping practices
- **Robots.txt Compliance**: Honors website crawling restrictions
- **Monitoring**: Detailed logging and statistics tracking
- **Graceful Degradation**: Continues processing even if some URLs fail

## 📋 Requirements

- **Python**: 3.8+
- **Pinecone Account**: API key and index setup
- **Gemini API Key**: Optional, for OCR functionality
- **Playwright Browsers**: Chromium for web scraping
- **Memory**: Sufficient RAM for in-memory processing

## 🚀 Getting Started Example

```bash
# 1. Start the API
python start_api.py

# 2. Index a website
curl -X POST "http://localhost:8000/index" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://verifylabs.ai/",
    "max_pages": 5,
    "use_namespaces": true,
    "namespace_prefix": "website_domain",
    "pinecone_index": "lawa-website-index"
  }'

# 3. Check results
curl http://localhost:8000/tasks/{task_id}
```

## 📚 API Documentation

Visit http://localhost:8000/docs for interactive API documentation with Swagger UI.

## 🔧 Development

### **Adding PDF Support**
To enable PDF processing in the main pipeline:

1. Remove PDF exclusion from URL collector
2. Add PDF detection in iterative processor
3. Integrate PDF processor for PDF URLs
4. Add file download capability

### **Custom Embedding Models**
To use different embedding models:

1. Update `EMBED_MODEL` in environment variables
2. Ensure model is compatible with Sentence Transformers
3. Update vector dimensions if needed

## 📄 License

MIT

---

**Note**: This system provides a complete, production-ready solution for website indexing with hybrid search capabilities, combining the best of semantic and keyword search for optimal results.