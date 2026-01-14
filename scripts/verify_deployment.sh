#!/bin/bash

# Verification Script for Lawa Webbotify Deployment
# Checks the health of all backend services and workers

echo "🔍 Starting Backend Verification Tests..."
echo "============================================"

# Function to check an endpoint
check_endpoint() {
    local name=$1
    local url=$2
    local expected_code=${3:-200}
    
    echo -n "Checking $name ($url)... "
    response=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    
    if [ "$response" == "$expected_code" ]; then
        echo "✅ OK (Status: $response)"
        return 0
    else
        echo "❌ FAILED (Status: $response)"
        return 1
    fi
}

# 1. Check Core Backend
check_endpoint "Core Backend API" "http://localhost:8000/api/health/" 200 || check_endpoint "Core Backend Root" "http://localhost:8000/" 200

# 2. Check Indexing Service
check_endpoint "Indexing Service" "http://localhost:8080/health" 200

# 3. Check Widget Service
check_endpoint "Widget Service" "http://localhost:8002/health" 200

# 4. Check Redis Connectivity
echo -n "Checking Redis Container... "
if docker-compose exec -T redis redis-cli ping | grep -q "PONG"; then
    echo "✅ OK (PONG received)"
else
    echo "❌ FAILED (Redis not responding)"
fi

# 5. Check Worker Logs for Errors
echo "--------------------------------------------"
echo "Checking Worker Logs for recent errors..."

echo -n "Core Worker Errors: "
core_errors=$(docker-compose logs --tail=50 backend-worker | grep -i "error" | wc -l)
if [ "$core_errors" -eq "0" ]; then
    echo "✅ None found in last 50 lines"
else
    echo "⚠️  Found $core_errors errors (check logs)"
fi

echo -n "Indexing Worker Errors: "
idx_errors=$(docker-compose logs --tail=50 indexing-worker | grep -i "error" | wc -l)
if [ "$idx_errors" -eq "0" ]; then
    echo "✅ None found in last 50 lines"
else
    echo "⚠️  Found $idx_errors errors (check logs)"
fi

echo "============================================"
echo "Verification Complete."
