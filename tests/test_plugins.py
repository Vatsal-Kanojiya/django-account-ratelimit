from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

from tests.test_limiter import hits_down


class DecoratorTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_fbv_html_429_with_retry_after(self):
        self.client.post("/fbv/")
        self.client.post("/fbv/")
        response = self.client.post("/fbv/")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "60")
        self.assertContains(response, "Too many requests", status_code=429)
        self.assertTemplateUsed(response, "account_ratelimit/429.html")

    def test_methods_not_listed_are_not_counted(self):
        for _ in range(5):
            self.assertEqual(self.client.get("/fbv/").status_code, 200)

    def test_cbv(self):
        codes = [self.client.get("/cbv/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_api_path_answers_json(self):
        for _ in range(2):
            self.client.get("/api/fbv/")
        response = self.client.get("/api/fbv/")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"detail": mock.ANY, "code": "rate_limited"})
        self.assertIn("Retry-After", response)

    @override_settings(TEMPLATES=[])
    def test_plain_text_when_there_is_no_template(self):
        for _ in range(3):
            response = self.client.post("/fbv/")
        self.assertEqual((response.status_code, response["Content-Type"]), (429, "text/plain"))

    def test_cache_down_on_a_closed_rule_is_503(self):
        rules = {"every-use": {"rate": "2/min", "key": "user-or-ip", "fail": "closed"}}
        with override_settings(RATELIMIT={"RULES": rules}), hits_down():
            with self.assertLogs("account_ratelimit", "ERROR"):
                response = self.client.post("/fbv/")
        self.assertEqual((response.status_code, response["Retry-After"]), (503, "30"))

    def test_ratelimit_headers_when_enabled(self):
        rules = {"every-use": {"rate": "2/min", "key": "user-or-ip"}}
        with override_settings(RATELIMIT={"RULES": rules, "HEADERS": True}):
            ok = self.client.post("/fbv/")
            self.client.post("/fbv/")
            refused = self.client.post("/fbv/")
        self.assertEqual((ok["RateLimit-Limit"], ok["RateLimit-Remaining"]), ("2", "1"))
        self.assertEqual(refused["RateLimit-Reset"], "60")

    def test_no_ratelimit_headers_by_default(self):
        self.assertNotIn("RateLimit-Limit", self.client.post("/fbv/"))


class DrfThrottleTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_429_with_retry_after(self):
        codes = [self.client.get("/api/drf/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        response = self.client.get("/api/drf/")
        self.assertEqual(response["Retry-After"], "60")
        self.assertEqual(response.json()["detail"].split(".")[0], "Request was throttled")

    def test_a_view_without_a_rule_is_not_throttled(self):
        codes = {self.client.get("/api/free/").status_code for _ in range(5)}
        self.assertEqual(codes, {200})

    def test_cache_down_on_a_closed_rule_is_503(self):
        rules = {"every-use": {"rate": "2/min", "key": "user-or-ip", "fail": "closed"}}
        with override_settings(RATELIMIT={"RULES": rules}), hits_down():
            with self.assertLogs("account_ratelimit", "ERROR"):
                response = self.client.get("/api/drf/")
        self.assertEqual((response.status_code, response["Retry-After"]), (503, "30"))


class MiddlewareTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("alice", password="pw")

    def test_signed_in_pages_are_limited(self):
        self.client.force_login(self.user)
        codes = [self.client.get("/pages/one/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_anonymous_visitors_are_not_counted(self):
        codes = {self.client.get("/pages/one/").status_code for _ in range(5)}
        self.assertEqual(codes, {200})

    def test_excluded_and_unmatched_paths(self):
        self.client.force_login(self.user)
        for _ in range(5):
            self.assertEqual(self.client.get("/pages/free/").status_code, 200)
            self.assertEqual(self.client.get("/api/free/").status_code, 200)

    def test_method_filter(self):
        paths = [{"pattern": r"^/pages/", "rule": "pages", "methods": ["post"]}]
        self.client.force_login(self.user)
        with override_settings(RATELIMIT={"RULES": {"pages": {"rate": "1/min", "key": "user"}}, "PATHS": paths}):
            codes = {self.client.get("/pages/one/").status_code for _ in range(3)}
        self.assertEqual(codes, {200})
