import base64
import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.persistence import LocalPersistenceService


class FixedUuid:
    hex = "abcdef1234567890"


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
