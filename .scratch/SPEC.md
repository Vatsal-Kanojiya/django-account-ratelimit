# SPEC — django-account-ratelimit V1

Status: draft for owner review (2026-10-23). Built from the owner's brief, a read of both
apps, and the owner's answers recorded in §9.

## 1. Problem

Both apps hand-roll the same limiter (`accounts/ratelimit.py`: super_notes 109 lines,
expense 319). Both count in `CACHES["default"]`, which falls back to LocMemCache because the
server sets no `CACHE_URL`. Under gunicorn `--workers 2` (from the systemd units), each
worker keeps its own counters. Every limit is therefore effectively doubled and resets on
restart. Both apps already ship a `check --deploy` warning for this, but the hint in both
suggests Redis DB 2, which is expense's Celery broker.

## 2. Goals / non-goals

Goals: one implementation for both apps; limits declared per feature in settings; counters
shared across processes; correct 429 + Retry-After for HTML and API; explicit behaviour
when the cache is down; existing limiter tests pass **unchanged**.

Non-goals: lockout admin UI, CAPTCHA, reputation services, PyPI, per-IP flood protection
(that's Cloudflare/Caddy's job), super_notes' monthly Ask quota (a DB-counted billing
allowance per plan: it stays in `assistant/quota.py`).

## 3. Concepts

- **Rule**: a named limit for one feature, e.g. `login`, `bill-scan`, `note-create`.
  Declared in `settings.RATELIMIT["RULES"]`. Each app declares only its own features. That
  is what makes the package modular.
- **Key**: *whose* budget a hit is counted against. Built from the request:
  `ip`, `user`, `account` (a typed identifier such as a username or email), `user-or-ip`,
  or a composite such as `ip+account`.
- **Two counting styles**, both already used by the apps:
  - *Failures only*: check before the work (`peek`), count only failures
    (`record`), forget on success (`reset`). Used for sign-in, MFA, password change and
    password reset.
  - *Every use*: count first and decide from the new total (`hit`), which is atomic, and
    give the unit back if no work happened (`refund`). Used for scans, exports and new notes.

## 4. Public API

### 4.1 Core (low level; the brief's signatures)

```python
from account_ratelimit import core
core.hit(scope, key, window) -> int            # atomic increment, returns new count
core.is_limited(scope, key, limit) -> bool     # read-only
core.reset(scope, key)                         # forget
core.refund(scope, key)                        # decrement, never below a missing key
core.retry_after(scope, key, window) -> int    # seconds until the window ends
```

- Fixed window that starts at the first hit (same as today). On the first hit a sibling
  `…:reset-at` key is `set()` with the window's end time, which is how Retry-After is known
  (Django's cache API has no TTL read). If the sibling is missing, Retry-After = window.
- `hit` = `cache.add(key, 0, window)` then `cache.incr(key)`, with today's `ValueError`
  fallback (`set(key, 1, window)`). On Redis, `incr` is a single INCRBY, so it's atomic
  across processes.
- Known gap, kept from today and documented: a fixed window allows up to 2× the limit across
  a window boundary.
- Cache key: `ratelimit:<scope>:<key>`. The prefix is configurable.

### 4.2 Rules layer (what app code uses)

```python
from account_ratelimit import limiter
d = limiter.hit("bill-scan", request)                    # every use, count-first
limiter.refund("bill-scan", request)
limiter.peek("login", request, account=username)         # failures only: read-only check
limiter.record("login", request, account=username)       # count one failure
limiter.reset("login", request, account=username)        # on success
```

Each call returns a `Decision(limited, count, limit, remaining, retry_after, rule,
reason)`, where `reason` is `None | "limit" | "unavailable"`.

### 4.3 Key builders (`account_ratelimit.keys`)

- `client_ip(request)`: moved verbatim from the apps. XFF read N entries from the right,
  N = `TRUSTED_PROXY_COUNT`, 0 → `REMOTE_ADDR`, never the left-most entry, `"unknown"` when
  no address is found.
- `account`: `strip().lower()`, then SHA-256 (hex). Hashing keeps email addresses out of
  Redis and keeps keys a fixed length, which is safe for every cache backend.
- `user`: `request.user.pk`. Anonymous → the rule doesn't apply (allowed, not counted).
- `user-or-ip`: user pk if signed in, else client IP.
- Composites are joined with `+` in config: `"ip+account"`.
- A rule's `key` may also be a dotted path to `callable(request, **ctx) -> str`.

### 4.4 Plug-ins

- **View decorator** `@ratelimit("rule", methods=("POST",), account=callable)`: works on
  functions, and on a class-based view class (it wraps `dispatch`). Every-use counting.
- **DRF throttle** `account_ratelimit.drf.RuleThrottle`: reads `view.ratelimit_rule`
  (an attribute or property, where `None` means not throttled) and raises DRF's `Throttled`
  with `wait()` = Retry-After. It deliberately does **not** read `throttle_scope`: DRF's
  `ScopedRateThrottle` raises ImproperlyConfigured for any scope missing from
  `DEFAULT_THROTTLE_RATES`, and super_notes' tests patch `ScopedRateThrottle.THROTTLE_RATES`
  directly. So existing DRF scopes stay on DRF in V1, and each scope moves to a rule later in
  its own PR (which updates those tests).
- **Middleware** `account_ratelimit.middleware.RateLimitMiddleware` (optional): applies
  rules from `RATELIMIT["PATHS"]`, a list of `{"pattern": regex, "rule": name,
  "methods": [...] | None}`. The first match wins. It must sit after
  `AuthenticationMiddleware`.

### 4.5 Responses

- Over the limit: **429** + `Retry-After` (in seconds, rounded up, at least 1).
- Cache down on a fail-closed rule: **503** + `Retry-After: 30`. This is honest that it's
  an outage and not the caller's fault. App shims instead report "blocked", so the existing
  views answer exactly as today.
- API vs HTML: the request is treated as an API call if the path starts with any of
  `RATELIMIT["API_PREFIXES"]` (default `["/api/"]`). API → JSON
  `{"detail": ..., "code": "rate_limited"}` (the shape both apps already use). HTML →
  template `account_ratelimit/429.html` (overridable), with a plain-text fallback.
- Optional `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset` headers, enabled by
  `RATELIMIT["HEADERS"] = True`.

## 5. Configuration

```python
RATELIMIT = {
    "CACHE": "default",              # alias in CACHES
    "PREFIX": "ratelimit",
    "ENABLED": True,                 # False: everything allowed, nothing counted
    "FAIL": "open",                  # default for non-auth rules
    "API_PREFIXES": ["/api/"],
    "HEADERS": False,
    "TEMPLATE": "account_ratelimit/429.html",
    "EXEMPT_STAFF": False,
    "EXEMPT_USERS": [],              # user pks
    "EXEMPT_IPS": [],                # exact addresses, as client_ip() reports them
    "ON_LIMITED": None,              # dotted path: fn(request, decision) — the audit hook
    "RULES": {
        "login": {"rate": "10/15m", "key": "ip+account", "auth": True},
        "bill-scan": {"rate": "30/h", "key": "user"},
    },
    "PATHS": [],
}
```

- Rate syntax: `<count>/<n?><unit>`, unit ∈ `s|sec|m|min|h|hour|d|day`.
  This accepts DRF's strings (`"5/min"`, `"3000/hour"`) and multiples (`"10/15m"`).
- Env overrides: each app wraps rates in `env("…", default=…)` in its own settings, the way
  `DEFAULT_THROTTLE_RATES` already does. The package doesn't read the environment.
- `auth: True` means: fail **closed** by default, and exemptions **never** apply. An admin
  account is exactly the one an attacker wants, so sign-in limits don't exempt staff. A
  rule's own `fail` and `exempt` settings override the global ones.
- Settings are validated at startup with a system check (`account_ratelimit.E00x`): an
  unparseable rate, an unknown key builder, a PATHS entry naming a missing rule, or an
  invalid FAIL value.

## 6. Cache down

Any exception from a cache operation other than the `ValueError` the core already handles
(for example redis-py `ConnectionError` or `TimeoutError`) is caught. The core then applies
the rule's fail mode: open → allowed and logged; closed → `Decision(limited=True,
reason="unavailable")`. Default: closed for `auth` rules, open for everything else
(decided by the owner). Each error is logged at ERROR level.

The deployment sets short Redis timeouts so that a dead Redis fails fast rather than
hanging a worker. The exact `CACHE_URL` options are to be verified against django-environ
0.14 in T9.

## 7. Observability

- One structured log line per trip, on logger `account_ratelimit`, at WARNING:
  `ratelimit tripped rule=<r> key=<builder output> count=<n> limit=<l> window=<s>
  retry_after=<s> path=<p>`. A "trip" is the hit that first takes a key over its limit,
  so it's logged once per window per key, not on every blocked request. Account identifiers
  only ever appear hashed.
- `ON_LIMITED` hook, called with `(request, decision)` on the same event. Each app points
  it at a small adapter in its `accounts/audit.py`. Errors raised inside the hook are logged
  and swallowed.

## 8. System checks

- `account_ratelimit.W001`: the RATELIMIT cache is LocMem or Dummy and `DEBUG=False`.
  Registered as a deploy check (`check --deploy`), as both apps' current checks are: a plain
  check would warn on every test run, because the test runner forces DEBUG=False on a
  local-memory cache. Hint: `CACHE_URL=redis://127.0.0.1:6379/<db>`. The apps'
  `.env` files name the actual DB (4 for super_notes, 5 for expense).
- The apps' existing checks (`config.W001`, `accounts.W001`) become shims that return the
  package's result with the old id. Their `@register` is removed so the warning isn't
  reported twice, and their tests call the functions directly, so those tests still pass.

## 9. Owner decisions (2026-10-23)

1. If Redis is down: sign-in style rules fail **closed**, everything else fails open.
2. V1 adds two **new** limits (§10.3):
   - super_notes `note-create`, per account (each new note queues a paid embedding call);
   - expense `web-pages`, per account, on the HTML pages, matching the API's 3000/hour.
3. super_notes' monthly Ask quota stays in super_notes.

Decided by Claude under "best practice" and open to veto: repo `~/django-account-ratelimit`
importing as `account_ratelimit`; app policy stays in the shims for V1; exemptions never on
auth rules; hashed account keys; DRF scopes stay on DRF in V1; Django's test runner (no
pytest anywhere, no new dependency); Redis test DB 6; Python ≥ 3.10 (expense's Dockerfile
uses python:3.10-slim).

## 10. Migration (per app, own branch/PR)

### 10.1 The shim (why it isn't a thin re-export)

Existing tests patch module constants (`patch.object(ratelimit, "LOGIN_LIMIT", …)`), assert
`LOGIN_ACCOUNT_LIMIT == 20`, call `ratelimit._account_key`, and call the old 5-argument
`is_limited(scope, request, identifier, limit, window)`. So each app's
`accounts/ratelimit.py` keeps:
- every public name and signature it has today;
- its constants, now *loaded from* `settings.RATELIMIT["RULES"]` at import time
  (`LOGIN_LIMIT, LOGIN_WINDOW = rules.limit_window("login")`). Settings become the single
  source of truth, and test patches still work because the functions read the module
  globals at call time;
- function bodies that delegate to `account_ratelimit.core` and `keys`;
- `client_ip` re-exported from the package (both `audit.py` files import it).

The shims are deleted in a later PR, together with tests rewritten against rules.

### 10.2 Rules each app declares

super_notes: `google-login-ip` 50/15m ip (auth).

expense: `login` 10/15m ip+account (auth), `login-ip` 50/15m ip (auth, shared with Google
sign-in as today), `login-account` 20/15m account (auth), `reset` 5/h ip+account (auth),
`signup` 10/h ip (auth), `password-change` 5/15m user (auth), `mfa` 5/15m user (auth),
`scan` 30/h user, `export` 20/h user.

All numbers are today's constants, unchanged.

### 10.3 New limits

- super_notes `note-create`: `RuleThrottle` on `NoteViewSet`, with `ratelimit_rule` set
  only when `action == "create"`. Key `user`. Default **300/hour, a starting guess and not
  measured**, env-overridable. Each create is its own POST, so a phone coming back online
  sends a burst. **Open risk:** how the web and Android clients handle a 429 during sync
  (do they retry later or drop the note?) must be checked before this ships (T11).
- expense `web-pages`: middleware PATHS entry for every path except `/api/`, `/static/`,
  `/media/` and the admin. Key `user`; anonymous visitors are not counted (per-IP flood is
  the edge's job). 3000/hour, matching `API_USER_THROTTLE`.

### 10.4 Deployment

`.env`: super_notes `CACHE_URL=redis://127.0.0.1:6379/4`, expense
`CACHE_URL=redis://127.0.0.1:6379/5` (plus the timeout options from T9). Restart the
`*-web` and `*-worker` services. The owner does this, or asks Claude to.

## 11. Acceptance

- [ ] Both apps' existing limiter tests pass unchanged on the package.
- [ ] One implementation: no counting logic left in either app.
- [ ] A test proves counters are shared across processes (two OS processes, one Redis DB 6).
- [ ] 429 + Retry-After for HTML and API (decorator, middleware, DRF).
- [ ] `check --deploy` warns on a per-process cache with DEBUG=False.
- [ ] Package suite green on Django 5.2 + DRF 3.17, Python 3.12 (3.10 is declared; the
      server has no 3.10 interpreter to run it on, so that's stated and not claimed as tested).
