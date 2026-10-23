from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from account_ratelimit import limiter

from .test_keys import FakeUser

RULES = {
    "every-use": {"rate": "2/min", "key": "user-or-ip"},
    "per-user": {"rate": "2/min", "key": "user"},
    "login": {"rate": "3/15m", "key": "ip+account", "auth": True},
}


def request(ip="10.0.0.1", user=None):
    req = RequestFactory().get("/somewhere/", REMOTE_ADDR=ip)
    req.user = user or AnonymousUser()
    return req


def cache_down():
    return mock.patch.object(cache, "get", side_effect=ConnectionError("down"))


def hits_down():
    return mock.patch.object(cache, "add", side_effect=ConnectionError("down"))


class EveryUseTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_count_first_then_decide(self):
        first, second, third = (limiter.hit("every-use", request()) for _ in range(3))
        self.assertEqual([d.limited for d in (first, second, third)], [False, False, True])
        self.assertEqual((second.count, second.remaining), (2, 0))
        self.assertEqual((third.reason, third.retry_after), ("limit", 60))

    def test_refund(self):
        limiter.hit("every-use", request())
        limiter.hit("every-use", request())
        limiter.refund("every-use", request())
        self.assertFalse(limiter.hit("every-use", request()).limited)

    def test_a_user_keyed_rule_does_not_count_anonymous_requests(self):
        for _ in range(5):
            decision = limiter.hit("per-user", request())
        self.assertEqual((decision.limited, decision.reason), (False, "not-applicable"))

    def test_a_user_keyed_rule_follows_the_account_across_addresses(self):
        alice = FakeUser(1)
        limiter.hit("per-user", request("10.0.0.1", alice))
        limiter.hit("per-user", request("10.0.0.2", alice))
        self.assertTrue(limiter.hit("per-user", request("10.0.0.3", alice)).limited)

    def test_user_without_a_request(self):
        limiter.hit("per-user", user=FakeUser(1))
        limiter.hit("per-user", user=FakeUser(1))
        self.assertTrue(limiter.hit("per-user", user=FakeUser(1)).limited)


class FailuresOnlyTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_peek_counts_nothing(self):
        for _ in range(5):
            self.assertFalse(limiter.peek("login", request(), account="alice").limited)

    def test_record_until_the_limit_then_peek_refuses(self):
        decisions = [limiter.record("login", request(), account="alice") for _ in range(3)]
        self.assertEqual([d.limited for d in decisions], [False, False, True])
        self.assertTrue(limiter.peek("login", request(), account="Alice ").limited)

    def test_other_accounts_and_addresses_are_unaffected(self):
        for _ in range(3):
            limiter.record("login", request(), account="alice")
        self.assertFalse(limiter.peek("login", request(), account="bob").limited)
        self.assertFalse(limiter.peek("login", request("10.0.0.9"), account="alice").limited)

    def test_reset_on_success(self):
        for _ in range(3):
            limiter.record("login", request(), account="alice")
        limiter.reset("login", request(), account="alice")
        self.assertFalse(limiter.peek("login", request(), account="alice").limited)


class CacheDownTests(SimpleTestCase):
    def test_auth_rules_fail_closed(self):
        with cache_down(), self.assertLogs("account_ratelimit", "ERROR"):
            decision = limiter.peek("login", request(), account="alice")
        self.assertEqual((decision.limited, decision.reason), (True, "unavailable"))
        self.assertEqual(decision.retry_after, 30)

    def test_other_rules_fail_open(self):
        with hits_down(), self.assertLogs("account_ratelimit", "ERROR"):
            decision = limiter.hit("every-use", request())
        self.assertEqual((decision.limited, decision.reason), (False, "unavailable"))

    @override_settings(RATELIMIT={"RULES": {"x": {"rate": "1/s", "key": "ip", "fail": "closed"}}})
    def test_a_rule_can_choose_closed(self):
        with hits_down(), self.assertLogs("account_ratelimit", "ERROR"):
            self.assertTrue(limiter.hit("x", request()).limited)

    def test_reset_and_refund_do_not_raise(self):
        with mock.patch.object(cache, "delete_many", side_effect=ConnectionError("down")):
            with self.assertLogs("account_ratelimit", "ERROR"):
                limiter.reset("login", request(), account="alice")


class ExemptionTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def staff(self):
        user = FakeUser(1)
        user.is_staff = True
        return user

    def exhaust(self, rule, req, **kw):
        return [limiter.hit(rule, req, **kw) for _ in range(5)][-1]

    @override_settings(RATELIMIT={"RULES": RULES, "EXEMPT_STAFF": True})
    def test_staff_exemption(self):
        decision = self.exhaust("every-use", request(user=self.staff()))
        self.assertEqual((decision.limited, decision.reason), (False, "exempt"))

    @override_settings(RATELIMIT={"RULES": RULES, "EXEMPT_STAFF": True})
    def test_never_on_auth_rules(self):
        decision = self.exhaust("login", request(user=self.staff()), account="admin")
        self.assertTrue(decision.limited)

    @override_settings(RATELIMIT={"RULES": RULES, "EXEMPT_USERS": [1], "EXEMPT_IPS": ["10.0.0.5"]})
    def test_user_and_ip_allowlists(self):
        self.assertFalse(self.exhaust("every-use", request(user=FakeUser(1))).limited)
        self.assertFalse(self.exhaust("every-use", request("10.0.0.5")).limited)
        self.assertTrue(self.exhaust("every-use", request("10.0.0.6")).limited)

    @override_settings(RATELIMIT={"RULES": RULES, "ENABLED": False})
    def test_disabled(self):
        self.assertEqual(self.exhaust("login", request(), account="a").reason, "disabled")


hook_calls = []


def hook(request, decision):
    hook_calls.append(decision)


def broken_hook(request, decision):
    raise RuntimeError("audit is down")


class TripTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        hook_calls.clear()

    @override_settings(RATELIMIT={"RULES": RULES, "ON_LIMITED": "tests.test_limiter.hook"})
    def test_one_log_line_and_one_hook_call_per_trip(self):
        with self.assertLogs("account_ratelimit", "WARNING") as logs:
            for _ in range(5):
                limiter.hit("every-use", request())
        self.assertEqual(len(logs.records), 1)
        self.assertIn("rule=every-use", logs.output[0])
        self.assertIn("count=3 limit=2", logs.output[0])
        self.assertEqual([d.count for d in hook_calls], [3])

    @override_settings(RATELIMIT={"RULES": RULES, "ON_LIMITED": "tests.test_limiter.hook"})
    def test_failures_trip_when_they_reach_the_limit(self):
        with self.assertLogs("account_ratelimit", "WARNING"):
            for _ in range(4):
                limiter.record("login", request(), account="Alice@Example.com")
        self.assertEqual([d.count for d in hook_calls], [3])
        self.assertNotIn("alice", hook_calls[0].key.lower().replace("acct:", ""))

    @override_settings(RATELIMIT={"RULES": RULES, "ON_LIMITED": "tests.test_limiter.broken_hook"})
    def test_a_broken_hook_is_logged_not_raised(self):
        with self.assertLogs("account_ratelimit", "ERROR") as logs:
            for _ in range(3):
                limiter.hit("every-use", request())
        self.assertTrue(any("hook" in line for line in logs.output))
