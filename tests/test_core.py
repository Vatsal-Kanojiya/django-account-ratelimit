from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from account_ratelimit import core


class CoreTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_hit_counts_and_is_limited_reads(self):
        self.assertFalse(core.is_limited("s", "k", 2))
        self.assertEqual(core.hit("s", "k", 60), 1)
        self.assertEqual(core.hit("s", "k", 60), 2)
        self.assertTrue(core.is_limited("s", "k", 2))
        self.assertEqual(core.count("s", "k"), 2)

    def test_scopes_and_keys_are_separate(self):
        core.hit("s", "a", 60)
        self.assertEqual(core.count("s", "b"), 0)
        self.assertEqual(core.count("t", "a"), 0)

    def test_reset_forgets(self):
        core.hit("s", "k", 60)
        core.reset("s", "k")
        self.assertEqual(core.count("s", "k"), 0)

    def test_refund_gives_one_back_and_never_goes_below_zero(self):
        core.hit("s", "k", 60)
        core.refund("s", "k")
        core.refund("s", "k")
        self.assertEqual(core.count("s", "k"), 0)

    def test_refund_on_a_missing_key_is_a_no_op(self):
        core.refund("s", "missing")
        self.assertIsNone(cache.get(core.full_key("s", "missing")))

    def test_the_window_does_not_restart_on_each_hit(self):
        with mock.patch("account_ratelimit.core.time.time", return_value=1000.0):
            core.hit("s", "k", 60)
        with mock.patch("account_ratelimit.core.time.time", return_value=1030.0):
            core.hit("s", "k", 60)
            self.assertEqual(core.retry_after("s", "k", 60), 30)

    def test_retry_after_without_a_window_record_is_the_whole_window(self):
        self.assertEqual(core.retry_after("s", "never", 60), 60)

    def test_retry_after_is_at_least_one(self):
        with mock.patch("account_ratelimit.core.time.time", return_value=1000.0):
            core.hit("s", "k", 60)
        with mock.patch("account_ratelimit.core.time.time", return_value=1059.9):
            self.assertEqual(core.retry_after("s", "k", 60), 1)

    def test_deleting_only_the_counter_unblocks(self):
        # expense's tests do this through _account_key().
        core.hit("s", "k", 60)
        cache.delete(core.full_key("s", "k"))
        self.assertEqual(core.hit("s", "k", 60), 1)

    def test_a_key_expiring_between_add_and_incr_starts_a_new_window(self):
        with mock.patch.object(cache, "incr", side_effect=ValueError):
            self.assertEqual(core.hit("s", "k", 60), 1)

    @override_settings(RATELIMIT={"PREFIX": "rl"})
    def test_prefix(self):
        self.assertEqual(core.full_key("s", "k"), "rl:s:k")

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}})
    def test_on_the_dummy_cache_every_hit_is_the_first(self):
        self.assertEqual(core.hit("s", "k", 60), 1)
        self.assertEqual(core.hit("s", "k", 60), 1)

    def test_cache_errors_become_cache_unavailable(self):
        with mock.patch.object(cache, "add", side_effect=ConnectionError("down")):
            with self.assertRaises(core.CacheUnavailable):
                core.hit("s", "k", 60)
        with mock.patch.object(cache, "get", side_effect=ConnectionError("down")):
            with self.assertRaises(core.CacheUnavailable):
                core.count("s", "k")
