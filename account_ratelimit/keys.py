"""Key builders: whose budget an attempt is counted against.

Keying is the design. By address alone, one office behind one NAT shares a
budget, and a botnet isn't stopped. By account alone, a stranger can lock any
account out by failing it on purpose. By both, a single source is slowed
against a single account, which is the shape of credential stuffing. A rule
picks one builder, or a composite such as ``"ip+account"``.

A builder returns None when it can't apply, e.g. ``user`` on an anonymous
request. The rule is then not counted for that request at all.
"""

import hashlib

from django.conf import settings
from django.utils.module_loading import import_string


def client_ip(request):
    """The caller's address, as far as the deployment can vouch for it.

    With no proxy in front (TRUSTED_PROXY_COUNT = 0), REMOTE_ADDR is the
    client, and X-Forwarded-For is ignored: it is whatever the client typed.

    Behind N trusted proxies, each appends the address it received the
    request from, so the entry N places from the right is the one the
    outermost trusted proxy saw. Everything to its left arrived with the
    request and is the client's to invent. Reading the left-most entry
    lets any caller pick the key its attempts are counted under.
    """
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if proxies > 0 and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-min(proxies, len(hops))]

    return request.META.get("REMOTE_ADDR", "unknown")


def normalise(identifier):
    # "Alice" and " alice" are the same account.
    return (identifier or "").strip().lower()


def account(identifier):
    """A typed identifier (username, email), hashed.

    Hashed so that email addresses never sit in the cache or the logs, and so
    that every key has a fixed length and safe characters for any backend.
    """
    return "acct:" + hashlib.sha256(normalise(identifier).encode()).hexdigest()


def user(user_or_pk):
    pk = getattr(user_or_pk, "pk", user_or_pk)
    return f"user:{pk}"


def _signed_in(request, user_obj):
    user_obj = user_obj if user_obj is not None else getattr(request, "user", None)
    if user_obj is None or not getattr(user_obj, "is_authenticated", False):
        return None
    return user_obj


def _ip(request, account_id, user_obj):
    return None if request is None else f"ip:{client_ip(request)}"


def _account(request, account_id, user_obj):
    return None if account_id is None else account(account_id)


def _user(request, account_id, user_obj):
    signed_in = _signed_in(request, user_obj)
    return None if signed_in is None else user(signed_in)


def _user_or_ip(request, account_id, user_obj):
    return _user(request, account_id, user_obj) or _ip(request, account_id, user_obj)


BUILDERS = {
    "ip": _ip,
    "account": _account,
    "user": _user,
    "user-or-ip": _user_or_ip,
}


def _builder(part):
    if part in BUILDERS:
        return BUILDERS[part]
    # A dotted path to fn(request, account, user) -> str | None.
    return import_string(part)


def validate_spec(spec):
    if callable(spec):
        return
    for part in spec.split("+"):
        if part not in BUILDERS and "." not in part:
            raise KeyError(f"unknown key builder {part!r}; use one of {sorted(BUILDERS)}")
        _builder(part)


def build(spec, request=None, *, account=None, user=None):
    """The rule's key for this request, or None if the rule doesn't apply."""
    builders = [spec] if callable(spec) else [_builder(part) for part in spec.split("+")]
    parts = [builder(request, account, user) for builder in builders]
    if any(part is None for part in parts):
        return None
    return "+".join(parts)
