#!/usr/bin/env python3
import sys
import subprocess
import re
import time
import os
import shutil

# ANSI Colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    GRAY = '\033[90m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Symbols
CHECK = "✓"
CROSS = "✗"
DOT = "•"
ARROW = "→"

def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80

def print_separator(char="─", color=Colors.BLUE):
    width = get_terminal_width()
    print(f"{color}{char * width}{Colors.ENDC}")

def format_test_name(nodeid):
    # nodeid format: path/to/file.py::ClassName::test_name or path/to/file.py::test_name
    parts = nodeid.split("::")
    path = parts[0]
    
    # Extract filename without extension
    filename = os.path.basename(path)
    
    if len(parts) > 1:
        test_name = " :: ".join(parts[1:])
    else:
        test_name = parts[0]
        
    return f"{Colors.GRAY}{filename} >{Colors.ENDC} {test_name}"

def run_with_output_processing(command, cwd=None, is_playwright=False):
    # Failures list to report at the end
    failures = []
    
    # Environment variables
    env = os.environ.copy()
    # Force line buffering for python
    env['PYTHONUNBUFFERED'] = '1'
    # Force colors in some tools if needed, though parsing color codes might be tricky.
    # We'll try to stick to parsing plain text if possible, but tools like pytest output color codes.
    
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        env=env,
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    current_file = ""
    
    # Regex for Pytest verbose output
    # Example: tests/test_core.py::test_example PASSED
    pytest_pattern = re.compile(r"^(.+?)::(.+) (PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS).*")
    
    # Regex for Playwright (line reporter)
    # Example: [chromium] › auth/login.spec.ts:15:3 › Login flow
    playwright_pattern = re.compile(r"^\[([a-z]+)\] › (.+) › (.+)")

    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if not line:
            continue
            
        line = line.strip()
        
        # --- PYTEST PARSING ---
        if not is_playwright:
            # Handle "collecting ..." lines
            if line.startswith("collecting"):
                print(f"{Colors.GRAY}  {line}{Colors.ENDC}")
                continue
                
            match = pytest_pattern.match(line)
            if match:
                path, test_name, status = match.groups()
                nodeid = f"{path}::{test_name}"
                
                # Check for cached/progress percentage at end of line (remove it)
                # status usually captures just the word, but logic might catch extra.
                # Actually regex above (PASSED...) matches the status. 
                
                clean_test_name = format_test_name(nodeid)
                
                if status == "PASSED":
                    print(f"  {Colors.GREEN}{CHECK}{Colors.ENDC} {clean_test_name}")
                elif status == "FAILED" or status == "ERROR":
                    print(f"  {Colors.RED}{CROSS}{Colors.ENDC} {clean_test_name}")
                    failures.append((nodeid, "Failed"))
                elif status == "SKIPPED":
                    print(f"  {Colors.YELLOW}{DOT}{Colors.ENDC} {clean_test_name}")
                elif status == "XFAIL":
                    print(f"  {Colors.YELLOW}x{Colors.ENDC} {clean_test_name} (Expected Fail)")
                elif status == "XPASS":
                    print(f"  {Colors.RED}X{Colors.ENDC} {clean_test_name} (Unexpected Pass)")
                    failures.append((nodeid, "Unexpected Pass"))
            
            # If line creates a "failure section" (Pytest typically prints "___ test_name ___")
            elif line.startswith("_ ") and line.endswith(" _"):
                 # This is start of failure details. We might want to capture or print nicely.
                 # For now, we assume user saw the cross mark. We can print this in GRAY.
                 pass # We print all other lines in gray below if we want, OR we suppress.
                 # User asked for "show the failed tests" at the end.
                 # Usually users want to see the stack trace. 
                 # Printing everything else as gray/dim is good.
                 print(f"{Colors.GRAY}{line}{Colors.ENDC}")
            elif "Error" in line or "Exception" in line or "Traceback" in line:
                 print(f"{Colors.RED}{line}{Colors.ENDC}")
            else:
                 # Print other output strictly? Or ignore?
                 # Ignoring might hide compilation errors or valuable info.
                 # Let's print indented gray.
                 if line:
                    # Ignore lines like "test session starts", "rootdir", etc to keep UI clean?
                    if line.startswith("===") or line.startswith("platform ") or line.startswith("rootdir:") or line.startswith("plugins:"):
                        pass
                    elif "passed," in line and "failed" in line:
                        # Summary line at bottom
                        print_separator()
                        print(f"{Colors.BOLD}{line}{Colors.ENDC}")
                    else:
                        print(f"{Colors.GRAY}    {line}{Colors.ENDC}")

        # --- PLAYWRIGHT PARSING ---
        else:
             # Match Playwright output
             # Depending on reporter used. 'line' reporter output:
             # [chromium] › tests/example.spec.ts:10:1 › has title
             # We can just print as is with color processing
             if "passed" in line.lower() or "✓" in line:
                 print(f"  {Colors.GREEN}{line}{Colors.ENDC}")
             elif "failed" in line.lower() or "✗" in line:
                 print(f"  {Colors.RED}{line}{Colors.ENDC}")
                 failures.append((line, "Failed"))
             else:
                 print(f"{Colors.GRAY}    {line}{Colors.ENDC}")

    rc = process.poll()
    
    if failures:
        print("\n")
        print(f"{Colors.RED}{Colors.BOLD}Failed Tests Summary:{Colors.ENDC}")
        for name, reason in failures:
            print(f"  {Colors.RED}{CROSS} {name}{Colors.ENDC}")
    
    return rc

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prettify.py <command>")
        sys.exit(1)
        
    cwd = sys.argv[1]
    is_playwright = sys.argv[2] == "true"
    cmd = " ".join(sys.argv[3:])
    
    print(f"{Colors.BLUE}{Colors.BOLD}Running: {cmd}{Colors.ENDC}")
    print_separator()
    
    try:
        rc = run_with_output_processing(cmd, cwd=cwd, is_playwright=is_playwright)
        sys.exit(rc)
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}Interrupted{Colors.ENDC}")
        sys.exit(130)
