# django-account-ratelimit

A pip-installable Django app for per-user / per-account rate limiting, shared by
~/super_notes and ~/expense_management. It is an extraction of both apps'
hand-written `accounts/ratelimit.py`, not a greenfield design: one implementation,
both apps' existing limiter tests passing on it unchanged.

Plan and progress live in `.scratch/` (SPEC.md, TICKETS.md, STATUS.md). Read
STATUS.md first when resuming.

## Owner rules

- **No new dependencies without asking first.** That includes django-redis,
  fakeredis, and adding this package to either app's requirements.
- **Conventional Commits** (`feat:`, `fix:`, `test:`, `docs:`, `chore:` ...).
- **Never add `Co-Authored-By` or "Generated with Claude" lines** to commits or PRs.
- **Commit or push only when the owner asks.**
- **Don't invent facts or numbers in docs.** A default limit that was chosen, not
  measured, is labelled as a starting guess.
- Replies stay short: done / pending / needs me.

## Technical rules

- Supports Python >= 3.10 (expense's Docker image is python:3.10-slim; the
  server venvs are 3.12), Django 5.2, DRF 3.17. DRF is optional at import time.
- `client_ip`: X-Forwarded-For read N entries from the right,
  N = `settings.TRUSTED_PROXY_COUNT` (0 -> REMOTE_ADDR). Never trust the left-most entry.
- Counters live in a shared cache. LocMem/Dummy is per process: the system check
  warns about it when DEBUG=False.
- Redis on 127.0.0.1:6379: DBs 0-3 are the Celery brokers/results of both apps.
  Production rate-limit caches: DB 4 (super_notes), DB 5 (expense). This package's
  own Redis tests use DB 6 and skip when Redis is unreachable.
- django-environ 0.14 maps `redis://` to Django's built-in
  `django.core.cache.backends.redis.RedisCache` (redis-py already installed), so
  no extra cache library is needed.
- Per-IP flood protection is Cloudflare/Caddy's job. Never touch ~/edge or Caddy.
- Out of scope: lockout admin UI, CAPTCHA, reputation services, PyPI, super_notes'
  monthly Ask quota (a DB-counted billing allowance, stays in the app).

## Commands

```bash
.venv/bin/python runtests.py        # Django's own runner; pytest is not installed anywhere
.venv/bin/python runtests.py tests.test_core   # one module
```
