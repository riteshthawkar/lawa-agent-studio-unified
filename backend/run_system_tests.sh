#!/bin/bash
set -e

# Ensure we are in the backend directory
cd "$(dirname "$0")"

# Activate venv
source venv/bin/activate

# Install test dependencies if missing (pytest)
if ! command -v pytest &> /dev/null; then
    echo "Installing pytest..."
    pip install pytest requests
fi

echo "🚀 Starting System Intregration Tests..."
echo "Target Base URL: ${TEST_API_BASE:-http://127.0.0.1:8000}"

# Run pytest on the system_tests directory
pytest system_tests/ -v -s

echo "✅ System Tests Completed Successfully!"
