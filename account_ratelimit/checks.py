"""System checks: a shared cache in production, and a valid RATELIMIT.

Every limit counts in one cache. A per-process cache (local memory, or the
dummy one) gives each gunicorn worker its own counters: the limits are
multiplied by the worker count and reset on every restart.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from .conf import config, validate

PER_PROCESS_CACHES = {
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.dummy.DummyCache",
}


# A deploy check, as both apps' own were: the test runner forces DEBUG=False
# on a local-memory cache, so a plain check would warn on every test run.
@register(Tags.caches, deploy=True)
def shared_cache(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    alias = config()["CACHE"]
    backend = settings.CACHES.get(alias, {}).get("BACKEND", "")
    if backend not in PER_PROCESS_CACHES:
        return []
    return [
        Warning(
            f"The {alias!r} cache ({backend.rsplit('.', 1)[-1]}) is not shared between "
            "processes, so each worker counts rate limits separately and they reset on restart.",
            hint="Point it at Redis, e.g. CACHE_URL=redis://127.0.0.1:6379/<db>.",
            id="account_ratelimit.W001",
        )
    ]


@register()
def valid_config(app_configs, **kwargs):
    return [Error(problem, id="account_ratelimit.E001") for problem in validate()]
