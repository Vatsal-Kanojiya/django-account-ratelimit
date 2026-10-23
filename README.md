# django-account-ratelimit

Per-user and per-account rate limiting for Django, shared by super_notes and the expense
tracker. Each app declares its own limits, one named **rule** per feature. The package does
the counting, the keys, the 429 response, the log line, and the warning when the cache isn't
shared between workers.

Django 5.2, Python ≥ 3.10. DRF 3.17 is optional (only for `account_ratelimit.drf`).

## Install

```bash
pip install "django-account-ratelimit @ git+file:///home/vatsal/django-account-ratelimit@<tag-or-commit>"
```

```python
INSTALLED_APPS = [..., "account_ratelimit"]
```

The counters live in a Django cache (`CACHES["default"]` unless `RATELIMIT["CACHE"]` says
otherwise). In production that cache must be shared by every worker, e.g. Redis:

```bash
CACHE_URL=redis://127.0.0.1:6379/<db>?socket_connect_timeout=1&socket_timeout=1
```

`check --deploy` warns (`account_ratelimit.W001`) when it's a local-memory or dummy cache.

## Rules

```python
RATELIMIT = {
    "RULES": {
        # Failures only, per address + account; refuses when the cache is down.
        "login": {"rate": env("RL_LOGIN", default="10/15m"), "key": "ip+account", "auth": True},
        # Every use, per signed-in account.
        "bill-scan": {"rate": "30/h", "key": "user"},
    },
}
```

- **rate**: `"5/min"`, `"3000/hour"`, `"10/15m"`, `"30/h"`, `"1/day"`. Fixed window, starting
  at the first hit. Across a window boundary a caller can get up to 2× the limit.
- **key**: `ip`, `user`, `account`, `user-or-ip`, composites like `ip+account`, or a dotted
  path to `fn(request, account, user) -> str | None`. Account identifiers are lower-cased,
  stripped and SHA-256 hashed. `ip` follows `settings.TRUSTED_PROXY_COUNT` (X-Forwarded-For
  read from the right; the left-most entry is never trusted). A rule whose key can't be built
  (`user` on an anonymous request) isn't counted.
- **auth**: `True` for sign-in style rules. These fail closed when the cache is down and are
  never exempt.
- **fail**: `"open"` or `"closed"`, overriding the default.
- **exempt**: `True` / `False`, overriding the global `EXEMPT_*` settings (ignored on auth
  rules).

Other settings, with their defaults: `CACHE="default"`, `PREFIX="ratelimit"`, `ENABLED=True`,
`FAIL="open"`, `UNAVAILABLE_RETRY_AFTER=30`, `API_PREFIXES=["/api/"]`, `HEADERS=False`,
`TEMPLATE="account_ratelimit/429.html"`, `EXEMPT_STAFF=False`, `EXEMPT_USERS=[]`,
`EXEMPT_IPS=[]`, `ON_LIMITED=None`, `PATHS=[]`. Invalid configuration is a system check
error (`account_ratelimit.E001`).

## Using a rule

```python
from account_ratelimit import limiter

# Every use: count first, decide from the new total (atomic).
decision = limiter.hit("bill-scan", request)
if decision.limited:
    ...
limiter.refund("bill-scan", request)            # no job was made after all

# Failures only: check, then count failures, then forget on success.
if limiter.peek("login", request, account=username).limited:
    ...
limiter.record("login", request, account=username)
limiter.reset("login", request, account=username)
```

A `Decision` has `limited`, `count`, `limit`, `remaining`, `retry_after`, `reason`
(`None`, `"limit"`, `"unavailable"`, `"exempt"`, `"disabled"`, `"not-applicable"`), `rule`
and `key`.

The low-level counter is `account_ratelimit.core`: `hit(scope, key, window) -> int`,
`is_limited(scope, key, limit)`, `count`, `reset`, `refund`, `retry_after`.

### View decorator

```python
from account_ratelimit.decorators import ratelimit

@ratelimit("export", methods=["POST"])
def export(request): ...

@ratelimit("export")               # on a class: wraps dispatch
class ExportView(View): ...
```

### DRF throttle

```python
REST_FRAMEWORK = {"DEFAULT_THROTTLE_CLASSES": [..., "account_ratelimit.drf.RuleThrottle"]}

class NoteViewSet(ModelViewSet):
    @property
    def ratelimit_rule(self):
        return "note-create" if self.action == "create" else None
```

It reads `ratelimit_rule`, not `throttle_scope`, so it can sit beside DRF's
`ScopedRateThrottle` while scopes move over one at a time.

### Middleware

```python
MIDDLEWARE = [..., "django.contrib.auth.middleware.AuthenticationMiddleware",
              "account_ratelimit.middleware.RateLimitMiddleware", ...]
RATELIMIT = {..., "PATHS": [
    {"pattern": r"^/", "rule": "web-pages", "exclude": [r"^/api/", r"^/static/"]},
]}
```

## Responses

Over the limit: **429** with `Retry-After`. Cache down on a fail-closed rule: **503** with
`Retry-After`. Paths under `API_PREFIXES` get JSON `{"detail": ..., "code": "rate_limited"}`;
other paths get the `TEMPLATE` page, or plain text if it's missing. Set `HEADERS=True` to add
`RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset`.

## Logging and audit

When a key first goes over its limit in a window, one WARNING line is logged on the
`account_ratelimit` logger, and `ON_LIMITED` (a dotted path to `fn(request, decision)`) is
called. Errors raised in the hook are logged, never raised. Cache failures are logged at
ERROR.

## Tests

```bash
python3.12 -m venv .venv
.venv/bin/pip install Django==5.2.17 djangorestframework==3.17.2 redis==5.2.1
.venv/bin/python runtests.py
```

`tests/test_redis.py` starts two OS processes against Redis DB 6 on 127.0.0.1:6379 and
checks that they share one count. It's skipped when Redis isn't reachable.
