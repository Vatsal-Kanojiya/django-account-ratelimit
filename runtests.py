#!/usr/bin/env python
"""Run the suite with Django's own runner: python runtests.py [labels...]."""

import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    django.setup()
    runner = get_runner(settings)(verbosity=2 if "-v" in sys.argv else 1)
    labels = [arg for arg in sys.argv[1:] if arg != "-v"] or ["tests"]
    sys.exit(bool(runner.run_tests(labels)))
