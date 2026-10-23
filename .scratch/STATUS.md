# STATUS

Updated 2026-10-23. Branch `feat/v1-core`. Nothing committed (owner rule: commit only when asked).

## Done: package, T1–T9
- 82 tests green (`runtests.py`), Django 5.2.17, DRF 3.17.2, redis 5.2.1, Python 3.12.
- The cross-process test ran for real against Redis DB 6 (two OS processes, one count). DB 6
  is left empty afterwards.
- Redis down, tested live on a closed port: an auth rule is refused in 0.09s, a non-auth
  rule is allowed.
- django-environ 0.14: `redis://127.0.0.1:6379/5?socket_connect_timeout=1&socket_timeout=1`
  gives RedisCache with integer OPTIONS. That's the CACHE_URL form to use (DB 4 super_notes,
  DB 5 expense).
- The wheel builds and includes the 429 template.
- Change from the spec draft: W001 is a deploy check (SPEC §8 updated); otherwise every test
  run would warn.

## Not done / not verified
- No lint: ruff isn't installed in any venv here (installing it would be a new dependency).
- Python 3.10 is declared but untested (no 3.10 interpreter on the server).

## Next: T10–T13 (app integrations)
Blocked on the owner: OK to install this package into each app's venv and requirements
(a dependency change). It also needs a first commit/tag here so a git URL can pin it.
