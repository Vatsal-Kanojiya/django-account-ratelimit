from django.test import SimpleTestCase, override_settings

from account_ratelimit.conf import ConfigError, get_rule, limit_window, parse_rate, validate


class ParseRateTests(SimpleTestCase):
    def test_drf_spellings_and_multiples(self):
        cases = {
            "5/min": (5, 60),
            "3000/hour": (3000, 3600),
            "10/15m": (10, 900),
            "30/h": (30, 3600),
            "1/day": (1, 86400),
            "2/30s": (2, 30),
            " 7 / 2 hours ": (7, 7200),
        }
        for rate, expected in cases.items():
            with self.subTest(rate=rate):
                self.assertEqual(parse_rate(rate), expected)

    def test_nonsense_is_refused(self):
        for rate in ("", "5", "five/min", "5/fortnight", "0/min", "5/0m", "-1/min"):
            with self.subTest(rate=rate), self.assertRaises(ConfigError):
                parse_rate(rate)


class RuleTests(SimpleTestCase):
    def test_auth_rules_fail_closed_and_are_never_exempt(self):
        rule = get_rule("login")
        self.assertEqual((rule.fail, rule.exempt), ("closed", False))

    def test_other_rules_follow_the_global_fail_mode(self):
        self.assertEqual(get_rule("every-use").fail, "open")
        with override_settings(RATELIMIT={"FAIL": "closed", "RULES": {"x": {"rate": "1/s"}}}):
            self.assertEqual(get_rule("x").fail, "closed")

    def test_an_auth_rule_cannot_be_made_exempt(self):
        rules = {"x": {"rate": "1/s", "auth": True, "exempt": True}}
        with override_settings(RATELIMIT={"RULES": rules}):
            self.assertIs(get_rule("x").exempt, False)

    def test_limit_window(self):
        self.assertEqual(limit_window("login"), (3, 900))

    def test_unknown_rule(self):
        with self.assertRaises(ConfigError):
            get_rule("nope")

    def test_the_test_settings_are_valid(self):
        self.assertEqual(validate(), [])

    def test_validate_reports_every_problem(self):
        bad = {
            "FAIL": "sideways",
            "RULES": {
                "a": {"rate": "lots"},
                "b": {"rate": "1/s", "key": "nonsense", "fail": "open"},
                "c": {"rate": "1/s", "fail": "maybe"},
            },
            "PATHS": [{"pattern": "(", "rule": "missing"}],
        }
        with override_settings(RATELIMIT=bad):
            problems = validate()
        self.assertEqual(len(problems), 6, problems)
