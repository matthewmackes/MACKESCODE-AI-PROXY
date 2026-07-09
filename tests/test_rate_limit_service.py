import unittest

from src.console.services.rate_limit import RateLimitService


class RateLimitServiceTests(unittest.TestCase):
    def test_disabled_limiter_allows_without_headers(self):
        service = RateLimitService({"enabled": False}, clock=lambda: 100)

        result = service.check("token-a", "GET", "/api/models")

        self.assertTrue(result["allowed"])
        self.assertEqual(result["headers"], {})

    def test_limits_by_key_method_and_path_with_headers(self):
        now = [100.0]
        service = RateLimitService({"enabled": True, "window_seconds": 60, "default_limit": 2}, clock=lambda: now[0])

        first = service.check("token-a", "GET", "/api/models")
        second = service.check("token-a", "GET", "/api/models")
        denied = service.check("token-a", "GET", "/api/models")
        other_path = service.check("token-a", "GET", "/api/status")
        other_token = service.check("token-b", "GET", "/api/models")

        self.assertTrue(first["allowed"])
        self.assertEqual(first["headers"]["x-ratelimit-limit"], "2")
        self.assertEqual(first["headers"]["x-ratelimit-remaining"], "1")
        self.assertTrue(second["allowed"])
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["headers"]["retry-after"], "60")
        self.assertEqual(denied["headers"]["x-ratelimit-remaining"], "0")
        self.assertTrue(other_path["allowed"])
        self.assertTrue(other_token["allowed"])

        now[0] = 161.0
        reset = service.check("token-a", "GET", "/api/models")
        self.assertTrue(reset["allowed"])
        self.assertEqual(reset["headers"]["x-ratelimit-remaining"], "1")

    def test_path_specific_and_write_limits(self):
        service = RateLimitService(
            {
                "enabled": True,
                "window_seconds": 60,
                "default_limit": 20,
                "write_limit": 5,
                "paths": {"/api/chat": {"limit": 3}},
            },
            clock=lambda: 100,
        )

        self.assertEqual(service.rule_for("GET", "/api/models")["limit"], 20)
        self.assertEqual(service.rule_for("POST", "/api/models")["limit"], 5)
        self.assertEqual(service.rule_for("POST", "/api/chat")["limit"], 3)


if __name__ == "__main__":
    unittest.main()
