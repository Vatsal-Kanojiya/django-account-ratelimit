from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

from account_ratelimit import keys


class FakeUser:
    is_authenticated = True
    is_staff = False

    def __init__(self, pk):
        self.pk = pk


class ClientIpTests(SimpleTestCase):
    """The same cases both apps test today."""

    def request(self, forwarded=None):
        extra = {"REMOTE_ADDR": "10.0.0.1"}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return RequestFactory().get("/", **extra)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_a_proxy_the_forwarded_header_is_ignored(self):
        self.assertEqual(keys.client_ip(self.request("203.0.113.9")), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_one_proxy_the_right_most_entry_is_used(self):
        request = self.request("1.2.3.4, 203.0.113.9")
        self.assertEqual(keys.client_ip(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_behind_two_proxies_the_second_from_the_right_is_used(self):
        request = self.request("1.2.3.4, 203.0.113.9, 172.18.0.5")
        self.assertEqual(keys.client_ip(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_a_forged_left_most_entry_is_never_used(self):
        request = self.request("6.6.6.6, 203.0.113.9, 172.18.0.5")
        self.assertNotEqual(keys.client_ip(request), "6.6.6.6")

    @override_settings(TRUSTED_PROXY_COUNT=3)
    def test_fewer_hops_than_proxies_uses_the_left_most_there_is(self):
        self.assertEqual(keys.client_ip(self.request("203.0.113.9, 172.18.0.5")), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_a_proxy_with_no_header_the_socket_address_is_used(self):
        self.assertEqual(keys.client_ip(self.request()), "10.0.0.1")

    def test_no_address_at_all(self):
        request = RequestFactory().get("/")
        del request.META["REMOTE_ADDR"]
        self.assertEqual(keys.client_ip(request), "unknown")


class BuildTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")
        self.request.user = AnonymousUser()

    def test_account_is_normalised_and_hashed(self):
        self.assertEqual(keys.account(" Alice "), keys.account("alice"))
        self.assertNotIn("alice", keys.account("alice"))
        self.assertEqual(len(keys.account("x" * 1000)), len(keys.account("y")))

    def test_ip(self):
        self.assertEqual(keys.build("ip", self.request), "ip:10.0.0.1")

    def test_user_needs_a_signed_in_user(self):
        self.assertIsNone(keys.build("user", self.request))
        self.request.user = FakeUser(7)
        self.assertEqual(keys.build("user", self.request), "user:7")

    def test_user_can_be_given_without_a_request(self):
        self.assertEqual(keys.build("user", user=FakeUser(8)), "user:8")

    def test_user_or_ip(self):
        self.assertEqual(keys.build("user-or-ip", self.request), "ip:10.0.0.1")
        self.request.user = FakeUser(7)
        self.assertEqual(keys.build("user-or-ip", self.request), "user:7")

    def test_composite(self):
        key = keys.build("ip+account", self.request, account="Alice")
        self.assertEqual(key, "ip:10.0.0.1+" + keys.account("alice"))

    def test_a_composite_missing_a_part_does_not_apply(self):
        self.assertIsNone(keys.build("ip+account", self.request))

    def test_a_dotted_path(self):
        self.assertEqual(keys.build("tests.test_keys.custom", self.request), "custom:10.0.0.1")

    def test_validate_spec(self):
        keys.validate_spec("ip+account")
        keys.validate_spec("tests.test_keys.custom")
        with self.assertRaises(KeyError):
            keys.validate_spec("ip+nonsense")


def custom(request, account, user):
    return f"custom:{keys.client_ip(request)}"
