#!/usr/bin/env python
"""
Comprehensive test runner for the Lawa Platform Backend
"""
import os
import sys
import django
from django.conf import settings
from django.test.utils import get_runner

def run_tests():
    """Run all comprehensive tests"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
    django.setup()
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    
    # Define test modules to run
    test_modules = [
        'apps.core.tests_comprehensive',
        'apps.core.tests_security',
        'apps.frontend.tests_comprehensive',
        'apps.indexing.tests_comprehensive',
        'apps.chatbot.tests_comprehensive',
        'apps.organizations.tests',
        'apps.sites.tests',
        'apps.chat.tests',
        'apps.usage.tests',
        'apps.webhooks.tests',
    ]
    
    print("🧪 Running Comprehensive Test Suite for Lawa Platform Backend")
    print("=" * 60)
    
    failures = test_runner.run_tests(test_modules, verbosity=2)
    
    if failures:
        print(f"\n❌ {failures} test(s) failed!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)

if __name__ == '__main__':
    run_tests()
