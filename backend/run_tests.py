#!/usr/bin/env python
"""
Comprehensive test runner for Lawa Platform Backend
"""
import os
import sys
import django
from django.conf import settings
from django.test.utils import get_runner

def run_tests():
    """Run all tests"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
    django.setup()
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    
    # Test modules to run
    test_modules = [
        'apps.core.tests',
        'apps.auth.tests',
        'apps.organizations.tests',
        'apps.sites.tests',
        'apps.indexing.tests',
        'apps.chatbot.tests',
        'apps.chat.tests',
        'apps.usage.tests',
        'apps.webhooks.tests',
        'apps.background_jobs.tests',
    ]
    
    print("Running Lawa Platform Backend Tests...")
    print("=" * 50)
    
    failures = test_runner.run_tests(test_modules)
    
    if failures:
        print(f"\n❌ {failures} test(s) failed!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)

if __name__ == '__main__':
    run_tests()
