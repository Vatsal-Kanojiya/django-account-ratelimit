from django.apps import AppConfig


class AccountRatelimitConfig(AppConfig):
    name = "account_ratelimit"
    verbose_name = "Rate limits"

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
