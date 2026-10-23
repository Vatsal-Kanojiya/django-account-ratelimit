"""``@ratelimit("rule")`` for function views and class-based views.

Counts every matching request (count-first, see limiter.hit). For counting
failures only, call limiter.peek / record / reset from the view instead.
"""

from functools import wraps

from . import limiter
from .responses import apply_headers, limited_response


def _guarded(view, rule, methods, account, *, is_method):
    @wraps(view)
    def wrapped(*args, **kwargs):
        request = args[1] if is_method else args[0]
        if methods is not None and request.method not in methods:
            return view(*args, **kwargs)
        decision = limiter.hit(
            rule, request, account=account(request) if account else None
        )
        if decision.limited:
            return limited_response(request, decision)
        return apply_headers(view(*args, **kwargs), decision)

    return wrapped


def ratelimit(rule, *, methods=None, account=None):
    """Limit a view by ``rule``.

    ``methods``: only these HTTP methods are counted (default: all).
    ``account``: ``fn(request) -> str`` for rules keyed on an account.
    On a class, it wraps ``dispatch`` so every handler is covered.
    """
    methods = {m.upper() for m in methods} if methods else None

    def decorate(view):
        if isinstance(view, type):
            view.dispatch = _guarded(view.dispatch, rule, methods, account, is_method=True)
            return view
        return _guarded(view, rule, methods, account, is_method=False)

    return decorate
