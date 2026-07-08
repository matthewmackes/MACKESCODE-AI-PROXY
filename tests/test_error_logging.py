import json
import unittest

from src.console.utils.error_logging import error_log_record, log_error_response


class FakeLogger:
    def __init__(self):
        self.messages = []

    def warning(self, message):
        self.messages.append(message)


class ErrorLoggingTests(unittest.TestCase):
    def test_error_log_record_omits_detail_values(self):
        record = error_log_record(
            "POST",
            "/api/chat",
            400,
            {"error": "bad", "message": "bad", "code": "bad_request", "category": "client", "details": {"token": "secret"}},
        )

        self.assertEqual(record["event"], "console_error_response")
        self.assertEqual(record["method"], "POST")
        self.assertEqual(record["path"], "/api/chat")
        self.assertEqual(record["status"], 400)
        self.assertEqual(record["code"], "bad_request")
        self.assertEqual(record["category"], "client")
        self.assertEqual(record["message"], "bad")
        self.assertEqual(record["details_keys"], ["token"])
        self.assertNotIn("secret", json.dumps(record))

    def test_log_error_response_writes_json_warning(self):
        logger = FakeLogger()

        record = log_error_response("GET", "/api/missing", 404, {"error": "missing"}, logger=logger)

        self.assertEqual(len(logger.messages), 1)
        self.assertEqual(json.loads(logger.messages[0]), record)


if __name__ == "__main__":
    unittest.main()
