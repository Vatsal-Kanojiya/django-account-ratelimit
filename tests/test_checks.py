from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import SimpleTestCase, override_settings

from account_ratelimit.checks import shared_cache, valid_config


def backend(path):
    return override_settings(CACHES={"default": {"BACKEND": path}})


class SharedCacheCheckTests(SimpleTestCase):
    def test_per_process_caches_are_flagged(self):
        for path in (
            "django.core.cache.backends.locmem.LocMemCache",
            "django.core.cache.backends.dummy.DummyCache",
        ):
            with self.subTest(path=path), backend(path):
                self.assertEqual([w.id for w in shared_cache(None)], ["account_ratelimit.W001"])

    @backend("django.core.cache.backends.redis.RedisCache")
    def test_redis_passes(self):
        self.assertEqual(shared_cache(None), [])

    @override_settings(DEBUG=True)
    def test_not_in_debug(self):
        self.assertEqual(shared_cache(None), [])

    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache"},
            "limits": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        },
        RATELIMIT={"CACHE": "limits"},
    )
    def test_it_checks_the_cache_the_limits_use(self):
        self.assertEqual(len(shared_cache(None)), 1)

    def test_check_deploy_reports_it(self):
        with self.assertRaisesMessage(SystemCheckError, "account_ratelimit.W001"):
            call_command("check", "--deploy", "--fail-level", "WARNING", verbosity=0)


class ConfigCheckTests(SimpleTestCase):
    def test_valid(self):
        self.assertEqual(valid_config(None), [])

    @override_settings(RATELIMIT={"RULES": {"x": {"rate": "lots"}}})
    def test_invalid(self):
        self.assertEqual([e.id for e in valid_config(None)], ["account_ratelimit.E001"])
