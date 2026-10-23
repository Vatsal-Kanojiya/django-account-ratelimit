"""Rules applied by path, from ``RATELIMIT["PATHS"]``.

Each entry: ``{"pattern": regex, "rule": name, "methods": [...] | None,
"exclude": [regex, ...]}``, matched with re.search against request.path.
The first matching entry wins. Place this after AuthenticationMiddleware,
or a rule keyed on the user never sees one.
"""

import re

from . import limiter
from .conf import config
from .responses import apply_headers, limited_response


def _matching_rule(request):
    for entry in config()["PATHS"]:
        if not re.search(entry["pattern"], request.path):
            continue
        if any(re.search(pattern, request.path) for pattern in entry.get("exclude", [])):
            continue
        methods = entry.get("methods")
        if methods and request.method not in {m.upper() for m in methods}:
            continue
        return entry["rule"]
    return None


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rule = _matching_rule(request)
        if rule is None:
            return self.get_response(request)
        decision = limiter.hit(rule, request)
        if decision.limited:
            return limited_response(request, decision)
        return apply_headers(self.get_response(request), decision)
