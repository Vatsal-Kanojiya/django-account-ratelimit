"""A DRF throttle backed by a rule.

It reads ``view.ratelimit_rule`` (an attribute or a property; None means not
throttled), deliberately not ``throttle_scope``: DRF's ScopedRateThrottle
raises ImproperlyConfigured for a scope missing from DEFAULT_THROTTLE_RATES,
so the two can't share the attribute while scopes migrate one by one.
"""

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.throttling import BaseThrottle

from . import limiter


class RateLimitUnavailable(APIException):
    """The cache is down and the rule fails closed. ``wait`` sets Retry-After."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Temporarily unavailable. Try again shortly."
    default_code = "unavailable"

    def __init__(self, wait):
        super().__init__()
        self.wait = wait


class RuleThrottle(BaseThrottle):
    decision = None

    def allow_request(self, request, view):
        rule = getattr(view, "ratelimit_rule", None)
        if not rule:
            return True
        self.decision = limiter.hit(rule, request)
        if self.decision.limited and self.decision.reason == "unavailable":
            raise RateLimitUnavailable(self.decision.retry_after)
        return not self.decision.limited

    def wait(self):
        return self.decision.retry_after if self.decision else None
