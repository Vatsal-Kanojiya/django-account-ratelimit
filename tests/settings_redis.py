"""Settings for the cross-process test: one real Redis, DB 6 (DBs 0-5 are in use)."""

from .settings import *  # noqa: F403

REDIS_URL = "redis://127.0.0.1:6379/6"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
RATELIMIT = {**RATELIMIT, "RULES": {**RATELIMIT["RULES"], "shared": {"rate": "10/min", "key": "user"}}}  # noqa: F405
