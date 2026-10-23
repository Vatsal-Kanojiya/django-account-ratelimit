"""The refusal: 429 when over the limit, 503 when the cache is down.

API paths answer JSON in the shape both apps already use; everything else
renders a template, falling back to plain text if the template is missing.
"""

from django.http import HttpResponse, JsonResponse
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from .conf import config

MESSAGES = {
    "limit": ("Too many requests. Try again later.", "rate_limited", 429),
    "unavailable": ("Temporarily unavailable. Try again shortly.", "unavailable", 503),
}


def is_api(request):
    return any(request.path.startswith(prefix) for prefix in config()["API_PREFIXES"])


def apply_headers(response, decision):
    """RateLimit-* headers, when RATELIMIT['HEADERS'] is on."""
    if not config()["HEADERS"] or decision.key is None:
        return response
    response["RateLimit-Limit"] = str(decision.limit)
    response["RateLimit-Remaining"] = str(decision.remaining)
    if decision.limited:
        response["RateLimit-Reset"] = str(decision.retry_after)
    return response


def limited_response(request, decision):
    detail, code, status = MESSAGES[
        "unavailable" if decision.reason == "unavailable" else "limit"
    ]
    if is_api(request):
        response = JsonResponse({"detail": detail, "code": code}, status=status)
    else:
        context = {"detail": detail, "retry_after": decision.retry_after, "status": status}
        try:
            body = render_to_string(config()["TEMPLATE"], context, request=request)
            response = HttpResponse(body, status=status)
        except TemplateDoesNotExist:
            response = HttpResponse(detail, status=status, content_type="text/plain")
    response["Retry-After"] = str(max(1, decision.retry_after))
    return apply_headers(response, decision)
