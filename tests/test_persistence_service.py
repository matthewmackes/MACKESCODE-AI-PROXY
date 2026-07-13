import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.console.services import persistence
from src.console.services.persistence import LocalPersistenceService


class FixedUuid:
    hex = "abcdef1234567890"


class FakeHeaders:
    def __init__(self, content_type):
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class FakeUrlResponse:
    """Minimal stand-in for the object returned by urllib.request.urlopen."""

    def __init__(self, body, content_type="image/png"):
        self._buffer = io.BytesIO(body)
        self.headers = FakeHeaders(content_type)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amt=None):
        return self._buffer.read(amt)


class LocalPersistenceServiceTests(unittest.TestCase):
    def service(self, tmp, now=1000):
        root = Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        return LocalPersistenceService(
            app_dir=lambda: root,
            chat_cost_per_mtok={"model-a": {"input": 0.5, "output": 1.5}},
            default_text_model=lambda: "model-a",
            clock=lambda: now,
            uuid_factory=lambda: FixedUuid(),
        )

    def test_history_append_read_and_delete_removes_image_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            image_dir = Path(tmp) / "images"
            image_dir.mkdir()
            (image_dir / "image-a.png").write_bytes(b"png")
            service.append_history({"id": "older", "created_at": 1, "filename": "older.png"})
            service.append_history({"id": "image-a", "created_at": 2, "filename": "image-a.png"})

            rows = service.read_history()
            deleted = service.delete_history_item("image-a")
            remaining = service.read_history()
            image_exists = (image_dir / "image-a.png").exists()

        self.assertEqual([row["id"] for row in rows], ["image-a", "older"])
        self.assertTrue(deleted)
        self.assertEqual([row["id"] for row in remaining], ["older"])
        self.assertFalse(image_exists)

    def test_save_image_item_decodes_base64_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            path = service.save_image_item({"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}, "img-1")
            data = path.read_bytes()

        self.assertEqual(path.name, "img-1.png")
        self.assertEqual(data, b"image-bytes")

    def test_save_image_item_rejects_file_url_without_fetching(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch("src.console.services.persistence.urlopen") as fake_urlopen:
                with self.assertRaisesRegex(ValueError, "only https"):
                    service.save_image_item({"url": "file:///etc/passwd"}, "img-file")
            leftovers = list((Path(tmp) / "images").iterdir())

        self.assertFalse(fake_urlopen.called)
        self.assertEqual(leftovers, [])

    def test_save_image_item_rejects_http_and_other_schemes(self):
        urls = (
            "http://169.254.169.254/latest/meta-data",
            "ftp://host/image.png",
            "data:image/png;base64,AAAA",
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch("src.console.services.persistence.urlopen") as fake_urlopen:
                for url in urls:
                    with self.assertRaisesRegex(ValueError, "only https"):
                        service.save_image_item({"url": url}, "img-bad")

        self.assertFalse(fake_urlopen.called)

    def test_save_image_item_rejects_oversize_response(self):
        body = b"x" * (persistence.MAX_IMAGE_DOWNLOAD_BYTES + 1)
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch(
                "src.console.services.persistence.urlopen",
                return_value=FakeUrlResponse(body, "image/png"),
            ):
                with self.assertRaisesRegex(ValueError, "exceeded"):
                    service.save_image_item({"url": "https://provider.example/big.png"}, "img-big")
            leftovers = list((Path(tmp) / "images").iterdir())

        self.assertEqual(leftovers, [])

    def test_save_image_item_rejects_non_image_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch(
                "src.console.services.persistence.urlopen",
                return_value=FakeUrlResponse(b"<html>nope</html>", "text/html"),
            ):
                with self.assertRaisesRegex(ValueError, "non-image content-type"):
                    service.save_image_item({"url": "https://provider.example/page"}, "img-html")
            leftovers = list((Path(tmp) / "images").iterdir())

        self.assertEqual(leftovers, [])

    def test_save_image_item_accepts_https_image_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch(
                "src.console.services.persistence.urlopen",
                return_value=FakeUrlResponse(b"png-bytes", "image/png"),
            ) as fake_urlopen:
                path = service.save_image_item({"url": "https://provider.example/img.png"}, "img-https")
            data = path.read_bytes()

        self.assertEqual(fake_urlopen.call_args[0][0], "https://provider.example/img.png")
        self.assertEqual(path.name, "img-https.png")
        self.assertEqual(data, b"png-bytes")

    def test_save_image_item_defaults_extension_to_png_for_unknown_image_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch(
                "src.console.services.persistence.urlopen",
                return_value=FakeUrlResponse(b"mystery-bytes", "image/x-mde-nonexistent"),
            ):
                path = service.save_image_item({"url": "https://provider.example/mystery"}, "img-x")

        self.assertEqual(path.name, "img-x.png")

    def test_save_image_item_prefers_b64_json_over_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with patch("src.console.services.persistence.urlopen") as fake_urlopen:
                path = service.save_image_item({
                    "b64_json": base64.b64encode(b"inline-bytes").decode("ascii"),
                    "url": "file:///etc/passwd",
                }, "img-both")
            data = path.read_bytes()

        self.assertFalse(fake_urlopen.called)
        self.assertEqual(path.name, "img-both.png")
        self.assertEqual(data, b"inline-bytes")

    def test_chat_cost_estimates_tokens_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            cost = service.chat_cost_usd("model-a", "one two three", "four five")

        self.assertEqual(cost["input_tokens_est"], 3)
        self.assertEqual(cost["output_tokens_est"], 2)
        self.assertEqual(cost["total_tokens_est"], 5)
        self.assertEqual(cost["total_cost_usd"], 0.0000045)

    def test_save_list_load_and_delete_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, now=2000)
            doc = service.save_chat({
                "messages": [
                    {"role": "user", "content": "Explain the build"},
                    {"role": "assistant", "content": "The build is ready"},
                ],
                "model": "model-a",
            })
            listed = service.list_chats()
            loaded = service.load_chat(doc["id"])
            deleted = service.delete_chat(doc["id"])

        self.assertEqual(doc["id"], "chat_2000_abcdef123456")
        self.assertEqual(doc["title"], "Explain the build")
        self.assertEqual(doc["total_tokens"], 8)
        self.assertEqual(listed[0]["message_count"], 2)
        self.assertEqual(loaded["id"], doc["id"])
        self.assertTrue(deleted)

    def test_fork_chat_preserves_source_metadata_and_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, now=2000)
            source = service.save_chat({
                "messages": [
                    {"role": "user", "content": "Explain the build"},
                    {"role": "assistant", "content": "Ready", "model": "model-a", "meta": {"trace": {"trace_id": "trace-a", "latency_ms": 123}, "routing": {"used": "model-a", "backend": "serverless"}, "cost": {"total_cost_usd": 0.01}}},
                    {"role": "user", "content": "Use another model"},
                ],
                "model": "model-a",
            })
            branch = service.fork_chat({
                "source_chat_id": source["id"],
                "message_index": 1,
                "model": "model-b",
                "notes": "try concise",
            })
            comparison = service.branch_comparison(source["id"])
            deleted = service.delete_chat(branch["id"])
            after_delete = service.branch_comparison(source["id"])

        self.assertEqual(branch["model"], "model-b")
        self.assertEqual(len(branch["messages"]), 2)
        self.assertEqual(branch["branch"]["parent_chat_id"], source["id"])
        self.assertEqual(branch["branch"]["source_message_index"], 1)
        self.assertEqual(branch["branch"]["source_trace_id"], "trace-a")
        self.assertEqual(branch["branch"]["source_route"]["backend"], "serverless")
        self.assertEqual(branch["branch"]["source_cost"]["total_cost_usd"], 0.01)
        self.assertEqual(branch["branch"]["source_latency_ms"], 123)
        self.assertEqual(branch["branch"]["selected_model"], "model-b")
        self.assertEqual(comparison["branches"][0]["id"], branch["id"])
        self.assertEqual(comparison["branches"][0]["branch"]["notes"], "try concise")
        self.assertEqual(comparison["branches"][0]["metrics"]["notes"], "try concise")
        self.assertIn("branch_delta_chars", comparison["branches"][0]["diff"])
        self.assertTrue(deleted)
        self.assertEqual(after_delete["branches"], [])

    def test_load_chat_handles_missing_or_malformed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            malformed = service.chat_filename("broken")
            malformed.write_text("{not json", encoding="utf-8")

            missing = service.load_chat("missing")
            broken = service.load_chat("broken")

        self.assertIsNone(missing)
        self.assertIsNone(broken)


if __name__ == "__main__":
    unittest.main()
