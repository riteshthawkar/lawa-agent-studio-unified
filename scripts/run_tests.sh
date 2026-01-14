#!/usr/bin/env bash
# =============================================================================
# Lawa Agent Studio - Unified Test Runner
# =============================================================================

set -e

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORMATTER="$PROJECT_ROOT/scripts/prettify_test_output.py"

# Colors
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}${BOLD}          🧪 LAWA AGENT STUDIO - TEST RUNNER                      ${NC}${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

run_core_tests() {
    echo -e "${BOLD}Running Django Core Tests...${NC}"
    
    if [ ! -d "$PROJECT_ROOT/backends/core/venv" ]; then
        echo "Virtual environment not found in backends/core. Please run 'make install-core'."
        return 1
    fi

    python3 "$FORMATTER" "$PROJECT_ROOT/backends/core" "false" "venv/bin/python -m pytest -v"
}

run_indexing_tests() {
    echo -e "${BOLD}Running Indexing Service Tests...${NC}"
    
    if [ ! -d "$PROJECT_ROOT/backends/indexing/env" ]; then
        echo "Virtual environment not found in backends/indexing. Please run 'make install-indexing'."
        return 1
    fi
    
    python3 "$FORMATTER" "$PROJECT_ROOT/backends/indexing" "false" "env/bin/python -m pytest tests/ -v"
}

run_widget_tests() {
    echo -e "${BOLD}Running Widget Backend Tests...${NC}"
    
    if [ ! -d "$PROJECT_ROOT/backends/widget/venv" ]; then
        echo "Virtual environment not found in backends/widget. Please run 'make install-widget'."
        # If no tests exist anyway, maybe skip? But if we are here, we expect tests.
        return 1
    fi
    
    # Check if tests exist
    if [ ! -d "$PROJECT_ROOT/backends/widget/tests" ] && ! ls "$PROJECT_ROOT/backends/widget"/test_*.py 1> /dev/null 2>&1; then
        echo "No tests found for Widget Backend."
        return 0
    fi
    
    python3 "$FORMATTER" "$PROJECT_ROOT/backends/widget" "false" "venv/bin/python -m pytest -v"
}

run_frontend_tests() {
    echo -e "${BOLD}Running Main Frontend Tests (Playwright)...${NC}"
    
    if [ ! -d "$PROJECT_ROOT/frontends/app/node_modules" ]; then
        echo "Node modules not found in frontends/app. Please run 'make install-frontend'."
        return 1
    fi
    
    python3 "$FORMATTER" "$PROJECT_ROOT/frontends/app" "true" "npx playwright test --reporter=line"
}

run_widget_frontend_tests() {
    echo -e "${BOLD}Running Widget Frontend Tests...${NC}"
    
    if [ ! -d "$PROJECT_ROOT/frontends/widget/node_modules" ]; then
        echo "Node modules not found in frontends/widget. Please run 'make install-widget-frontend'."
        return 1
    fi
    
    # Assuming 'npm run test' works and uses a standard runner (like Vitest)
    # We treat it as 'false' for is_playwright unless we know it uses Playwright.
    # Vitest output is similar to pytest/generic.
    python3 "$FORMATTER" "$PROJECT_ROOT/frontends/widget" "false" "npm run test"
}

main() {
    local component="${1:-all}"
    
    print_header
    
    case $component in
        "all")
            run_core_tests || true
            echo ""
            run_indexing_tests || true
            echo ""
            run_widget_tests || true
            echo ""
            run_frontend_tests || true
            echo ""
            run_widget_frontend_tests || true
            ;;
        "core")
            run_core_tests
            ;;
        "indexing")
            run_indexing_tests
            ;;
        "widget")
            run_widget_tests
            ;;
        "frontend")
            run_frontend_tests
            echo ""
            run_widget_frontend_tests
            ;;
        "quick")
            python3 "$FORMATTER" "$PROJECT_ROOT/backends/core" "false" "venv/bin/python -m pytest -v -x"
            ;;
        *)
            echo "Usage: $0 [all|core|indexing|widget|frontend|quick]"
            exit 1
            ;;
    esac
}

main "$@"
