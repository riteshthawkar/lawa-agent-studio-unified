#!/bin/bash
set -e

export PINECONE_API_KEY=pcsk_5NtFnh_QT3TvKWwXEpEiNU8GfodkF8HnRFVAFotTT4gZQpZQZtqjW1ZdUjdRmp1scqReji


echo "🧪 Starting Integrated Testing Environment..."

# Check requirements
if [ -z "$PINECONE_API_KEY" ]; then
    echo "⚠️ PINECONE_API_KEY is not set in environment. Tests interacting with Pinecone may fail."
    echo "Usage: PINECONE_API_KEY=your_key ./scripts/run_integration_tests.sh"
    # Don't exit, maybe user put it in .env.test manually
fi

# 1. Start test infrastructure (DB, Redis)
echo "🚀 Starting test infrastructure..."
docker-compose -f docker-compose.test.yml up -d test-db test-redis

echo "⏳ Waiting for database and redis (5s)..."
ls -la
sleep 5

# 2. Start application services
echo "🚀 Starting application services..."
docker-compose -f docker-compose.test.yml up -d test-backend test-indexing test-chatbot

echo "⏳ Waiting for services to initialize (15s)..."
sleep 15

# 3. Health checks
echo "🔍 Checking service health..."

check_health() {
    url=$1
    name=$2
    if curl -s -f "$url" > /dev/null; then
        echo "✅ $name is healthy"
        return 0
    else
        echo "❌ $name is NOT healthy ($url)"
        docker-compose -f docker-compose.test.yml logs $name
        return 1
    fi
}

check_health "http://localhost:8100/health/" "test-backend" || exit 1
check_health "http://localhost:8180/health" "test-indexing" || exit 1
check_health "http://localhost:8102/health" "test-chatbot" || exit 1

echo "✅ All services are up and running!"

# 4. Prepare Test Data
echo "🛠️ Creating test data..."
# Use docker exec to run a setup script inside the container if needed
# docker-compose -f docker-compose.test.yml exec -T test-backend python manage.py create_test_data

# 5. Run Integration Tests
echo "🧪 Running integration tests..."
cd backend
if [ "$1" == "--run-all" ]; then
    echo "Running complete test suite..."
    TEST_CMD="python manage.py test"
else
    echo "Running system tests..."
    TEST_CMD="python manage.py test system_tests --settings=lawa_platform.settings"
fi

# Run the python command locally, connecting to the dockerized services
# We need to export the test env vars for the local runner
export $(grep -v '^#' ../.env.test | xargs)
export DB_HOST=localhost
export DB_PORT=5433
export REDIS_URL=redis://localhost:6380/1

$TEST_CMD

TEST_EXIT_CODE=$?

# 6. Cleanup
if [ "$2" == "--keep" ]; then
    echo "Example: ./scripts/run_integration_tests.sh --run-all --keep"
    echo "🛑 Keeping environment running for manual inspection."
    echo "Backend: http://localhost:8100"
    echo "Indexing: http://localhost:8180"
    echo "Chatbot: http://localhost:8102"
else
    echo "🧹 Cleaning up..."
    cd ..
    docker-compose -f docker-compose.test.yml down -v
fi

exit $TEST_EXIT_CODE
