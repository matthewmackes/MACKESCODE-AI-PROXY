import base64
import tempfile
import types
import unittest
from pathlib import Path

from backend.v2.services.code_attachments import CodeAttachmentStore


PNG_1X1 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
).decode("ascii")


class V2CodeAttachmentStoreTests(unittest.TestCase):
    def test_create_lists_data_uri_and_deletes_session_scoped_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CodeAttachmentStore(
                root_dir=Path(tmp),
                clock=lambda: 123.0,
                uuid_factory=lambda: types.SimpleNamespace(hex="attachment-a"),
            )
            attachment = store.create({
                "session_id": "work/session",
                "filename": "screen.png",
                "mime_type": "image/png",
                "data": PNG_1X1,
            }, actor={"id": "owner"})

            listed = store.list("work/session")
            data_uri = store.data_uri("work/session", "attachment-a")
            deleted = store.delete("work/session", "attachment-a")

        self.assertEqual(attachment["id"], "attachment-a")
        self.assertEqual(attachment["width"], 1)
        self.assertEqual(attachment["height"], 1)
        self.assertEqual(attachment["actor_id"], "owner")
        self.assertEqual(listed[0]["filename"], "screen.png")
        self.assertTrue(data_uri.startswith("data:image/png;base64,"))
        self.assertTrue(deleted["deleted"])

    def test_rejects_unsupported_type_and_oversized_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CodeAttachmentStore(root_dir=Path(tmp))
            with self.assertRaises(ValueError):
                store.create({"mime_type": "text/plain", "data": PNG_1X1})

            store.max_bytes = 2
            with self.assertRaises(ValueError):
                store.create({"mime_type": "image/png", "data": PNG_1X1})


if __name__ == "__main__":
    unittest.main()
