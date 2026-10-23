"""Counters are shared across processes when the cache is Redis.

This is the production bug the package exists to fix: under LocMem each
gunicorn worker counts alone. Two real OS processes hit one rule here and
must see one count. Skipped when no Redis is listening on 127.0.0.1:6379.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from tests import settings_redis

ROOT = Path(__file__).resolve().parent.parent
RULES = {"shared": {"rate": "10/min", "key": "user"}}


def redis_client():
    try:
        import redis

        client = redis.Redis.from_url(settings_redis.REDIS_URL, socket_connect_timeout=1)
        client.ping()
        return client
    except Exception:
        return None


@unittest.skipUnless(redis_client(), "Redis is not reachable on 127.0.0.1:6379")
@override_settings(CACHES=settings_redis.CACHES, RATELIMIT={"RULES": RULES})
class SharedAcrossProcessesTests(SimpleTestCase):
    def setUp(self):
        from account_ratelimit import core

        core.reset("shared", "user:1")
        self.addCleanup(core.reset, "shared", "user:1")

    def run_worker(self, hits):
        return subprocess.Popen(
            [sys.executable, "-m", "tests.redis_worker", "shared", str(hits)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_two_processes_share_one_count(self):
        workers = [self.run_worker(8), self.run_worker(8)]
        outputs = [w.communicate(timeout=60) for w in workers]
        for (out, err), worker in zip(outputs, workers, strict=True):
            self.assertEqual(worker.returncode, 0, err)

        rows = [tuple(map(int, line.split())) for out, _ in outputs for line in out.splitlines()]
        counts = sorted(count for count, _ in rows)
        # 16 hits from two processes: one counter that reached 16, every value seen once.
        self.assertEqual(counts, list(range(1, 17)))
        # Exactly the hits past the limit of 10 were refused, whichever process sent them.
        self.assertEqual(sum(limited for _, limited in rows), 6)

    def test_a_third_process_sees_the_window_the_others_used(self):
        first = self.run_worker(10)
        first.communicate(timeout=60)
        out, err = self.run_worker(1).communicate(timeout=60)
        self.assertEqual(out.split(), ["11", "1"], err)
