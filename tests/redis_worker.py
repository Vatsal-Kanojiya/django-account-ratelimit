"""One OS process: hit a rule N times against the shared Redis and print each decision."""

import os
import sys

import django

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_redis"
django.setup()

from account_ratelimit import limiter  # noqa: E402

rule, hits = sys.argv[1], int(sys.argv[2])
for _ in range(hits):
    decision = limiter.hit(rule, user=type("U", (), {"pk": 1, "is_authenticated": True})())
    print(decision.count, int(decision.limited), flush=True)
