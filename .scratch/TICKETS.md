# TICKETS — V1

Each ticket is done when its tests are green. The order is the build order.
Spec references are to SPEC.md.

## Package (~/django-account-ratelimit)

- [x] **T1 Scaffold.** Package layout, `apps.py`, `runtests.py` (Django runner, settings in
  `tests/settings.py`), a `.venv` with Django 5.2.17, DRF 3.17.2 and redis 5.2.1 (the
  exact versions both apps already run, so nothing new is introduced), and README.md.
  Done when: `runtests.py` runs an empty suite.
- [x] **T2 Rates + config.** Parse rate strings (§5), load and validate `RATELIMIT`, and add
  `conf.get_rule(name)` and `conf.limit_window(name)`. Config errors are system check E001.
- [x] **T3 Core.** `hit` / `is_limited` / `reset` / `refund` / `retry_after` (§4.1), including
  the sibling reset-at key and the `ValueError` fallback. Tests on LocMem and Dummy.
- [x] **T4 Keys.** `client_ip` copied verbatim along with both apps' client_ip tests, plus
  `account` (hashed), `user`, `user-or-ip`, composites and dotted-path callables.
- [x] **T5 Rules layer + fail mode + exemptions.** `limiter.hit/peek/record/reset/refund`
  returning `Decision`. Fail open/closed on a cache error (test with a backend that raises).
  Staff, user and IP exemptions, never applied to auth rules.
- [x] **T6 Trip logging + ON_LIMITED hook.** Logged once per window per key; a hook that
  raises is swallowed and logged.
- [x] **T7 Responses + plug-ins.** 429/503 builder (JSON vs template, Retry-After, optional
  RateLimit-* headers), the decorator (FBV + CBV), `RuleThrottle` (DRF), and the middleware
  with PATHS.
- [x] **T8 System check W001.** Plus the startup config check from T2.
- [x] **T9 Redis.** The cross-process test: two `subprocess` Python processes that hit the same
  rule on Redis DB 6 and must see one shared count; skipped when Redis is unreachable.
  Verify what `env.cache_url("redis://…/4?…")` produces in django-environ 0.14 (backend
  class, and whether socket timeout options pass through as integers) and record the exact
  `CACHE_URL` to use.

## super_notes integration (branch `feat/shared-ratelimit`)

- **T10 Shim.** Add the package to the venv (**needs owner OK: installing this package
  into the app counts as a new dependency**). Rewrite `accounts/ratelimit.py` as a shim
  (§10.1), declare the RATELIMIT rules in settings, turn `config/checks.py`'s cache check
  into a shim, and wire `ON_LIMITED` to audit. Every existing test passes unchanged.
- **T11 note-create.** Add the rule, the throttle on `NoteViewSet.create` and new tests.
  Check how the web and Android clients treat a 429 during sync, and report back before
  enabling.

## expense integration (branch `feat/shared-ratelimit`)

- **T12 Shim.** Same as T10, for the larger module (login, reset, signup, password
  change, MFA, scan, export, Google).
- **T13 web-pages.** Middleware with PATHS excluding `/api/`, `/static/`, `/media/` and
  admin, signed-in users only. New tests.

## Deploy (owner, or Claude when asked)

- **T14** Set `CACHE_URL` in both `.env` files (DBs 4 and 5), run `check --deploy` (no
  W001), and restart the web and worker services. Fix the comment in expense's settings,
  which says "three workers" while the unit runs 2.

## Later (not V1)

- Move DRF scopes `auth` / `search` / `ask` from `ScopedRateThrottle` to rules, rewriting
  their tests.
- Delete the shims; rewrite their tests against rules.
