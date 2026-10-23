SECRET_KEY = "tests-only"
DEBUG = False
USE_TZ = True
ROOT_URLCONF = "tests.urls"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "account_ratelimit",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "account_ratelimit.middleware.RateLimitMiddleware",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_THROTTLE_CLASSES": ["account_ratelimit.drf.RuleThrottle"],
}
TRUSTED_PROXY_COUNT = 0
RATELIMIT = {
    "RULES": {
        "every-use": {"rate": "2/min", "key": "user-or-ip"},
        "per-user": {"rate": "2/min", "key": "user"},
        "login": {"rate": "3/15m", "key": "ip+account", "auth": True},
        "pages": {"rate": "2/min", "key": "user"},
    },
    "PATHS": [{"pattern": r"^/pages/", "rule": "pages", "exclude": [r"^/pages/free/"]}],
}
# The trip log line is asserted with assertLogs; keep it out of the test output.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "loggers": {"account_ratelimit": {"handlers": ["null"], "propagate": False}},
}
