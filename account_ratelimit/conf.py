"""Settings: one ``settings.RATELIMIT`` dict, read on every call.

Read on every call rather than once at import, so ``override_settings`` in
a test changes behaviour the way it would for any other Django setting.
Parsing a dict and a short regex per request costs nothing next to the
cache round trip that follows it.
"""

import re
from dataclasses import dataclass

from django.conf import settings

DEFAULTS = {
    "CACHE": "default",
    "PREFIX": "ratelimit",
    "ENABLED": True,
    "FAIL": "open",
    "UNAVAILABLE_RETRY_AFTER": 30,
    "API_PREFIXES": ["/api/"],
    "HEADERS": False,
    "TEMPLATE": "account_ratelimit/429.html",
    "EXEMPT_STAFF": False,
    "EXEMPT_USERS": [],
    "EXEMPT_IPS": [],
    "ON_LIMITED": None,
    "RULES": {},
    "PATHS": [],
}

_UNITS = {
    "s": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}  # fmt: skip

# "5/min", "3000/hour" (DRF's spelling), and multiples such as "10/15m".
_RATE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*([a-z]+)\s*$")

FAIL_MODES = ("open", "closed")


class ConfigError(ValueError):
    pass


def config():
    return {**DEFAULTS, **getattr(settings, "RATELIMIT", {})}


def parse_rate(rate):
    """``"10/15m"`` -> ``(10, 900)``: a count and a window in seconds."""
    match = _RATE.match(str(rate).lower())
    if not match or match[3] not in _UNITS:
        raise ConfigError(f"Invalid rate {rate!r}; expected e.g. '5/min' or '10/15m'.")
    limit, multiple = int(match[1]), int(match[2] or 1)
    if limit < 1 or multiple < 1:
        raise ConfigError(f"Invalid rate {rate!r}; count and window must be at least 1.")
    return limit, multiple * _UNITS[match[3]]


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window: int
    key: str
    auth: bool
    fail: str
    # None: the global EXEMPT_* settings decide. Auth rules are never exempt.
    exempt: bool | None


def get_rule(name):
    conf = config()
    try:
        raw = conf["RULES"][name]
    except KeyError:
        raise ConfigError(f"No rate limit rule named {name!r} in RATELIMIT['RULES'].") from None

    limit, window = parse_rate(raw["rate"])
    auth = bool(raw.get("auth", False))
    fail = raw.get("fail") or ("closed" if auth else conf["FAIL"])
    if fail not in FAIL_MODES:
        raise ConfigError(f"Rule {name!r}: fail must be 'open' or 'closed', not {fail!r}.")
    exempt = False if auth else raw.get("exempt")
    return Rule(name, limit, window, raw.get("key", "user-or-ip"), auth, fail, exempt)


def limit_window(name):
    rule = get_rule(name)
    return rule.limit, rule.window


def validate():
    """Every configuration problem, as messages for the startup check."""
    from . import keys

    conf = config()
    problems = []
    if conf["FAIL"] not in FAIL_MODES:
        problems.append(f"RATELIMIT['FAIL'] must be 'open' or 'closed', not {conf['FAIL']!r}.")
    for name, raw in conf["RULES"].items():
        try:
            rule = get_rule(name)
            keys.validate_spec(rule.key)
        except (ConfigError, KeyError, ImportError) as exc:
            problems.append(f"Rule {name!r}: {exc}")
    for entry in conf["PATHS"]:
        if entry.get("rule") not in conf["RULES"]:
            problems.append(f"RATELIMIT['PATHS'] entry {entry!r} names an unknown rule.")
        for pattern in [entry.get("pattern", "")] + list(entry.get("exclude", [])):
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"RATELIMIT['PATHS'] pattern {pattern!r}: {exc}")
    return problems
