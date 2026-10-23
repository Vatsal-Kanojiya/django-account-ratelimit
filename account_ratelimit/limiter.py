"""Rules: what app code calls.

Two ways of counting, both used by the apps:

* **Every use** -- ``hit()`` counts first and decides from the new total, in
  one cache operation. Reading the count and adding to it later would let
  two requests sent at the same moment both see room for one. ``refund()``
  gives a unit back when the request then made no job.
* **Failures only** -- ``peek()`` before the work (read-only), ``record()``
  after a failure, ``reset()`` on success. Used where only wrong answers
  should count: passwords, codes, tokens.

Every call returns a Decision. When the cache is down, the rule's fail mode
decides: "closed" (the default for auth rules) refuses, "open" allows.
"""

import logging
from dataclasses import dataclass

from django.utils.module_loading import import_string

from . import core, keys
from .conf import config, get_rule

logger = logging.getLogger("account_ratelimit")


@dataclass(frozen=True)
class Decision:
    rule: str
    limited: bool
    limit: int
    window: int
    count: int = 0
    retry_after: int = 0
    # None, "limit", "unavailable" (the cache is down), or "exempt".
    reason: str | None = None
    key: str | None = None

    @property
    def remaining(self):
        return max(0, self.limit - self.count)


def _exempt(rule, request, user):
    if rule.exempt is False:
        return False
    if rule.exempt is True:
        return True
    conf = config()
    user = user if user is not None else getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        if conf["EXEMPT_STAFF"] and user.is_staff:
            return True
        if user.pk in conf["EXEMPT_USERS"]:
            return True
    return request is not None and keys.client_ip(request) in conf["EXEMPT_IPS"]


def _resolve(name, request, account, user):
    """(rule, key), or (rule, None) with a reason when nothing is counted."""
    rule = get_rule(name)
    if not config()["ENABLED"]:
        return rule, None, "disabled"
    if _exempt(rule, request, user):
        return rule, None, "exempt"
    key = keys.build(rule.key, request, account=account, user=user)
    return rule, key, None if key is not None else "not-applicable"


def _allowed(rule, reason=None, key=None, count=0):
    return Decision(rule.name, False, rule.limit, rule.window, count, 0, reason, key)


def _unavailable(rule, key, exc):
    logger.error(
        "ratelimit cache unavailable rule=%s fail=%s error=%s", rule.name, rule.fail, exc
    )
    limited = rule.fail == "closed"
    retry_after = config()["UNAVAILABLE_RETRY_AFTER"] if limited else 0
    return Decision(rule.name, limited, rule.limit, rule.window, 0, retry_after, "unavailable", key)


def _limited(rule, key, count):
    try:
        retry_after = core.retry_after(rule.name, key, rule.window)
    except core.CacheUnavailable:
        retry_after = rule.window
    return Decision(rule.name, True, rule.limit, rule.window, count, retry_after, "limit", key)


def _trip(request, decision):
    """Once per window per key: the moment the key becomes limited."""
    logger.warning(
        "ratelimit tripped rule=%s key=%s count=%s limit=%s window=%s retry_after=%s path=%s",
        decision.rule,
        decision.key,
        decision.count,
        decision.limit,
        decision.window,
        decision.retry_after,
        getattr(request, "path", "-"),
    )
    hook = config()["ON_LIMITED"]
    if hook:
        try:
            import_string(hook)(request, decision)
        except Exception:
            logger.exception("ratelimit ON_LIMITED hook %s failed", hook)


def hit(name, request=None, *, account=None, user=None):
    """Spend one unit; limited once the new total is over the limit."""
    rule, key, reason = _resolve(name, request, account, user)
    if key is None:
        return _allowed(rule, reason)
    try:
        count = core.hit(rule.name, key, rule.window)
    except core.CacheUnavailable as exc:
        return _unavailable(rule, key, exc)
    if count <= rule.limit:
        return _allowed(rule, key=key, count=count)
    decision = _limited(rule, key, count)
    if count == rule.limit + 1:
        _trip(request, decision)
    return decision


def peek(name, request=None, *, account=None, user=None):
    """Whether the key has already used up its attempts. Counts nothing."""
    rule, key, reason = _resolve(name, request, account, user)
    if key is None:
        return _allowed(rule, reason)
    try:
        count = core.count(rule.name, key)
    except core.CacheUnavailable as exc:
        return _unavailable(rule, key, exc)
    if count < rule.limit:
        return _allowed(rule, key=key, count=count)
    return _limited(rule, key, count)


def record(name, request=None, *, account=None, user=None):
    """Count one failure; limited once the failures reach the limit."""
    rule, key, reason = _resolve(name, request, account, user)
    if key is None:
        return _allowed(rule, reason)
    try:
        count = core.hit(rule.name, key, rule.window)
    except core.CacheUnavailable as exc:
        return _unavailable(rule, key, exc)
    if count < rule.limit:
        return _allowed(rule, key=key, count=count)
    decision = _limited(rule, key, count)
    if count == rule.limit:
        _trip(request, decision)
    return decision


def reset(name, request=None, *, account=None, user=None):
    """Forget the key's count, e.g. after a successful sign-in."""
    _quietly("reset", name, request, account, user)


def refund(name, request=None, *, account=None, user=None):
    """Give back one unit spent by hit() on a request that then did nothing."""
    _quietly("refund", name, request, account, user)


def _quietly(action, name, request, account, user):
    # A reset or refund that can't reach the cache leaves the count a little
    # high until the window ends. That isn't worth failing the request for.
    rule, key, _ = _resolve(name, request, account, user)
    if key is None:
        return
    try:
        getattr(core, action)(rule.name, key)
    except core.CacheUnavailable as exc:
        logger.error("ratelimit cache unavailable on %s rule=%s error=%s", action, name, exc)
