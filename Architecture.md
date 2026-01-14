# Lawa AI Platform - System Architecture

## 1. High-Level System Architecture

The Lawa AI Platform uses a **Microservices-oriented Architecture** deployed on a single DigitalOcean Droplet using Docker Compose. It orchestrates three main functional areas: **Management** (Django), **Indexing** (FastAPI+Celery), and **Inference** (FastAPI).

### System Container Diagram

```mermaid
C4Context
    title System Container Diagram (Lawa AI Platform)

    Person(user, "User", "Platform Administrator or Dashboard User")
    Person(visitor, "Website Visitor", "End-user chatting with the widget")

    System_Boundary(lawa_platform, "Lawa AI Platform (Single Droplet)") {
        
        Container(nginx, "Nginx / Load Balancer", "Reverse Proxy", "Routes traffic to appropriate services")
        
        System_Boundary(backend_services, "Backend Services") {
            Container(django, "Core Backend", "Django", "User mgmt, Orchestration, Billing (Port 8000)")
            Container(indexing_api, "Indexing API", "FastAPI", "Receives crawl requests, manages queue (Port 8080)")
            Container(chatbot_api, "Chatbot API", "FastAPI", "RAG Inference, Chat History (Port 8002)")
        }

        System_Boundary(workers, "Async Workers") {
            Container(django_worker, "Django Worker", "Celery", "Emailing, periodic tasks")
            Container(indexing_worker, "Indexing Worker", "Celery", "Headed Browsers (Playwright), Scraping, Embedding")
        }

        System_Boundary(data, "Data Persistence") {
            ContainerDb(redis, "Redis", "Redis 7", "Message Broker & Cache (Port 6379)")
            ContainerDb(postgres, "PostgreSQL", "PostgreSQL 15 (Managed)", "Relational Data (Users, Projects, Logs)")
        }
    }

    System_Ext(pinecone, "Pinecone", "Vector Database (SaaS)")
    System_Ext(llm, "LLM Provider", "OpenAI / Gemini API")

    Rel(user, django, "Configures Projects", "HTTPS/JSON")
    Rel(visitor, chatbot_api, "Sends Messages", "HTTPS/JSON")
    
    Rel(django, postgres, "Reads/Writes User Data", "SQL")
    Rel(django, redis, "Queues Tasks (DB 1)", "Redis Protocol")
    Rel(django, indexing_api, "Triggers Indexing", "HTTP/Internal")
    
    Rel(indexing_api, redis, "Queues Crawl Tasks (DB 2)", "Redis Protocol")
    Rel(indexing_worker, redis, "Consumes Tasks", "Redis Protocol")
    Rel(indexing_worker, pinecone, "Upserts Vectors", "HTTPS")
    Rel(indexing_worker, django, "Webhooks Progress", "HTTP/Internal")

    Rel(chatbot_api, pinecone, "Semantic Search", "HTTPS")
    Rel(chatbot_api, llm, "Generates Answers", "HTTPS")
    Rel(chatbot_api, postgres, "Logs Chat History", "SQL")
```

---

## 2. Infrastructure & Deployment

The system is unified under a single `docker-compose.yml`.

### Network Topology
*   **Docker Network (`lawa-network`)**: Private bridge network.
*   **Service Discovery**: `http://indexing-service:8080`, `http://chatbot-service:8002`.
*   **Peristence**:
    *   **Postgres**: External Managed DB.
    *   **Redis**: Local Container.

---

## 3. Data Architecture (ER Diagram)

This diagram highlights the key relationships between Projects, Indexing Jobs, and Chat Sessions.

```mermaid
erDiagram
    User ||--o{ Project : owns
    Project ||--o{ ChatBot : has
    Project ||--o{ IndexingJob : initiates
    
    IndexingJob ||--o{ CrawledPage : processes
    
    ChatBot ||--o{ ChatSession : manages
    ChatSession ||--o{ ChatMessage : contains
    
    Project {
        uuid id PK
        string name
        string api_key
    }

    IndexingJob {
        uuid id PK
        string status "PENDING|PROCESSING|COMPLETED"
        string url
        int pages_crawled
    }

    ChatSession {
        string session_id PK
        timestamp created_at
        string visitor_id
    }

    ChatMessage {
        int id PK
        string sender "USER|BOT"
        text content
        json source_citations
        timestamp timestamp
    }
```

---

## 4. Workflows & Data Application

### A. Website Indexing Workflow (Parallel Processing)

This flow details how a URL is turned into vector embeddings.

```mermaid
sequenceDiagram
    autonumber
    participant User as User/Frontend
    participant Django as Django Core
    participant IndexAPI as Indexing API
    participant Redis as Redis Queue
    participant Worker as Celery Worker
    participant Embed as Gemini/OpenAI
    participant Pinecone as Pinecone
    participant DB as Postgres DB

    note over User, Django: Phase 1: Submission
    User->>Django: POST /api/projects/{id}/index/ (URL)
    Django->>DB: Create Job (PENDING)
    Django->>IndexAPI: POST /index/start_job
    IndexAPI->>Redis: LPUSH task_queue
    IndexAPI-->>Django: 200 OK (Task Queued)
    Django-->>User: 202 Accepted (Job ID)

    note over Worker, Pinecone: Phase 2: Execution (Async)
    Worker->>Redis: BRPOP task_queue
    Worker->>Worker: Launch Playwright
    
    loop Every Page
        Worker->>Worker: Navigate & Scrape Content
        Worker->>Embed: Generate Embeddings
        Embed-->>Worker: Vector List
        Worker->>Pinecone: Upsert Vectors
    end

    note over Worker, Django: Phase 3: Reporting
    Worker->>Django: Webhook: Progress Update (50%)
    Django->>DB: Update Job (PROCESSING)
    
    Worker->>Django: Webhook: Job Complete
    Django->>DB: Update Job (COMPLETED)
```

### B. RAG Chat Workflow (Retrieval Augmented Generation)

This flow handles the real-time chat response generation.

```mermaid
flowchart TD
    A[User Message] --> B(Chatbot API)
    B --> C{History Exists?}
    C -- Yes --> D[Load Chat History from DB]
    C -- No --> E[Create New Session]
    D --> F[Generate Query Embedding]
    E --> F
    
    F --> G[Pinecone Vector Search]
    G --> H[Retrieve Top-K Context Chunks]
    
    H --> I[Construct LLM Prompt]
    I --> J[System Prompt + Context + History + User Query]
    
    J --> K[Call LLM (OpenAI/Gemini)]
    K --> L[Generate Response]
    
    L --> M[Save Message to DB]
    M --> N[Return Response to User]
```

---

## 5. Key Integration Points

### 1. Authentication
*   **Django**: Uses JWT (SimpleJWT) for Dashboard access.
*   **Inter-Service**: Services use **API Tokens** (defined in `.env` as `INDEXING_API_TOKEN`, etc.) to trust requests between Django and Indexing API.

### 2. State Management
*   **Indexing State**: Maintained in Postgres (`IndexingJob` table).
*   **Chat History**: Stored in Postgres (`ChatMessage` table).

### 3. Scalability
*   The **Indexing Worker** is decoupled from the API. Scale workers horizontally:
    ```bash
    docker-compose up -d --scale indexing-worker=3
    ```







# 1. Tear down EVERYTHING (removes containers, networks, and orphans)
docker-compose down --remove-orphans

# 2. Check if anything survived (should be empty or unrelated containers only)
docker ps -a

# 3. If you see ANY container related to 'lawa' or 'redis' in step 2, copy its ID and kill it:
# docker rm -f <CONTAINER_ID>

# 4. Rebuild and start fresh
docker-compose up -d --build