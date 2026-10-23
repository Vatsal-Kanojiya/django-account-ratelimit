"""The counter: a cache key per (scope, key), and a fixed window.

**Fixed, not sliding.** The counter expires as a whole rather than ageing
entry by entry, so a determined caller can get up to 2x the limit across a
window boundary. A sliding window costs a sorted set per key and is not
worth it here, but the gap should be known rather than assumed away.

**add() then incr().** incr() raises on a missing key, and set() would reset
the expiry on every attempt: the window would restart for ever and the limit
would be unreachable. On Redis, incr() is one INCRBY, so two processes
counting at the same moment both get counted.

**Retry-After.** Django's cache API can't read a key's remaining lifetime,
so the first hit of a window also stores the window's end time beside the
counter.

Every cache failure other than incr()'s own ValueError is raised as
CacheUnavailable. Whether that blocks or allows is the rule's decision
(limiter.py), not the counter's.
"""

import math
import time

from django.core.cache import caches

from .conf import config


class CacheUnavailable(Exception):
    pass


def _cache():
    return caches[config()["CACHE"]]


def full_key(scope, key):
    return f"{config()['PREFIX']}:{scope}:{key}"


def _reset_at_key(cache_key):
    return f"{cache_key}:reset-at"


def _start_window(cache, cache_key, window):
    cache.set(_reset_at_key(cache_key), time.time() + window, window)


def hit(scope, key, window):
    """Count one against ``key`` and return the new total."""
    cache_key = full_key(scope, key)
    try:
        cache = _cache()
        if cache.add(cache_key, 0, window):
            _start_window(cache, cache_key, window)
        try:
            return cache.incr(cache_key)
        except ValueError:
            # The key expired between add() and incr(). Rare, and the right
            # response is to treat this as the first hit of a new window.
            cache.set(cache_key, 1, window)
            _start_window(cache, cache_key, window)
            return 1
    except Exception as exc:
        raise CacheUnavailable(str(exc)) from exc


def count(scope, key):
    """The current total, without counting anything. Read-only."""
    try:
        return _cache().get(full_key(scope, key)) or 0
    except Exception as exc:
        raise CacheUnavailable(str(exc)) from exc


def is_limited(scope, key, limit):
    """Whether ``key`` has already used up ``limit``. Read-only."""
    return count(scope, key) >= limit


def reset(scope, key):
    cache_key = full_key(scope, key)
    try:
        _cache().delete_many([cache_key, _reset_at_key(cache_key)])
    except Exception as exc:
        raise CacheUnavailable(str(exc)) from exc


def refund(scope, key):
    """Give one back, for a counted request that then did no work."""
    cache_key = full_key(scope, key)
    try:
        cache = _cache()
        try:
            if cache.decr(cache_key) < 0:
                cache.incr(cache_key)
        except ValueError:
            # Expired in between: nothing to give back.
            pass
    except Exception as exc:
        raise CacheUnavailable(str(exc)) from exc


def retry_after(scope, key, window):
    """Whole seconds until ``key``'s window ends; at least 1."""
    try:
        reset_at = _cache().get(_reset_at_key(full_key(scope, key)))
    except Exception as exc:
        raise CacheUnavailable(str(exc)) from exc
    if reset_at is None:
        return window
    return max(1, math.ceil(reset_at - time.time()))
