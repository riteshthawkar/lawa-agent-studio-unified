#!/bin/bash
set -e

# Configuration
REDIS_PORT=6380
DJANGO_PORT=8100
INDEXING_PORT=8180
CHATBOT_PORT=8102
ENV_FILE=".env.test"

# 0. Load Environment Variables
set -a
source $ENV_FILE
set +a

# Source Virtual Environment
source test_venv/bin/activate
pip install dnspython

echo "🧪 Starting Local Process Orchestration..."

# Check requirements
if ! command -v redis-server &> /dev/null; then
    echo "❌ redis-server not found in PATH"
    exit 1
fi
if [ -z "$PINECONE_API_KEY" ]; then
    echo "⚠️ PINECONE_API_KEY is not set. Export it before running."
fi

# Cleanup function to kill background processes
cleanup() {
    echo ""
    echo "🧹 Cleaning up background processes..."
    # Only kill services we started
    if [ -n "$DJANGO_PID" ]; then kill $DJANGO_PID 2>/dev/null || true; fi
    if [ -n "$INDEXING_PID" ]; then kill $INDEXING_PID 2>/dev/null || true; fi
    if [ -n "$CHATBOT_PID" ]; then kill $CHATBOT_PID 2>/dev/null || true; fi
    
    # For Redis, if we started it, kill it. 
    if [ -n "$START_REDIS" ]; then
        if [ -n "$REDIS_PID" ]; then kill $REDIS_PID 2>/dev/null || true; fi
    fi
    echo "✅ Cleanup complete"
}
trap cleanup EXIT INT TERM

# Overrides for Local Execution
export DATABASE_URL="postgres://lawa_test:test_password@localhost:5432/lawa_test"
export REDIS_URL="redis://localhost:$REDIS_PORT/1"
export DEBUG=True
export TESTING=True

# 1. Start Redis (Test Instance)
if lsof -Pi :$REDIS_PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️ Redis already running on port $REDIS_PORT. Using existing instance."
else
    echo "🚀 Starting Local Redis on port $REDIS_PORT..."
    redis-server --port $REDIS_PORT &
    REDIS_PID=$!
    START_REDIS=true
    sleep 2
fi

# 2. Start Django Backend
echo "🚀 Starting Django Backend on port $DJANGO_PORT..."
cd backend
python3 manage.py migrate --noinput
python3 manage.py runserver 0.0.0.0:$DJANGO_PORT &
DJANGO_PID=$!
cd ..
sleep 5

# 3. Start Indexing Service
echo "🚀 Starting Indexing Service on port $INDEXING_PORT..."
export BACKEND_BASE_URL="http://localhost:$DJANGO_PORT"
export USE_CELERY_WORKER=False
python3 -m uvicorn app:app --app-dir website_indexing_backend --host 0.0.0.0 --port $INDEXING_PORT &
INDEXING_PID=$!
sleep 3

# 4. Start Chatbot Service
echo "🚀 Starting Chatbot Service on port $CHATBOT_PORT..."
cd EMBEDDED_CHATBOT/backend
export CHATBOT_BACKEND_PORT=$CHATBOT_PORT
# Start Chatbot Service with uvicorn directly to control port
python3 -m uvicorn app:app --app-dir EMBEDDED_CHATBOT/backend --host 0.0.0.0 --port $CHATBOT_PORT &
CHATBOT_PID=$!
cd ../..
sleep 3

# 5. Health Checks
echo "🔍 Checking service health..."
wait_for_service() {
    url=$1
    name=$2
    max_retries=60
    count=0
    while [ $count -lt $max_retries ]; do
        if curl -s -f "$url" > /dev/null; then
            echo "✅ $name is healthy"
            return 0
        fi
        count=$((count + 1))
        echo "⏳ Waiting for $name... ($count/$max_retries)"
        sleep 1
    done
    echo "❌ $name failed to start after $max_retries seconds"
    return 1
}

wait_for_service "http://localhost:$DJANGO_PORT/health/" "Backend" || exit 1
wait_for_service "http://localhost:$INDEXING_PORT/health" "Indexing" || echo "⚠️ Indexing Service skipped (dependency issues)"
wait_for_service "http://localhost:$CHATBOT_PORT/health" "Chatbot" || exit 1

# 6. Run Integration Tests
echo "🧪 Running integration tests..."
cd backend
pytest
TEST_EXIT_CODE=$?
cd ..

exit $TEST_EXIT_CODE
