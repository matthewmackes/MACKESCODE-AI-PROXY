import tempfile
import unittest
from pathlib import Path

from src.console.handlers.static_handler import StaticHandler


class StaticHandlerTests(unittest.TestCase):
    def test_file_response_returns_bytes_and_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.png").write_bytes(b"png-data")
            handler = StaticHandler(root)

            response = handler.file_response("sample.png", default_content_type="image/png")

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"], b"png-data")
        self.assertEqual(response["content_type"], "image/png")
        self.assertEqual(response["headers"]["content-length"], "8")

    def test_file_response_returns_none_for_missing_file(self):
        handler = StaticHandler("/tmp")
        self.assertIsNone(handler.file_response("missing-file.png"))

    def test_path_resolution_uses_basename_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "safe.txt").write_text("ok", encoding="utf-8")
            handler = StaticHandler(root)

            response = handler.file_response("../safe.txt", default_content_type="text/plain")

        self.assertEqual(response["data"], b"ok")


if __name__ == "__main__":
    unittest.main()
