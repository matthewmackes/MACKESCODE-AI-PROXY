import json
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.irc_bridge import IrcBridgeConfigStore, IrcMetadataLog, IrcModelDirectory, parse_irc_line, text_chunks


class FakeShowcase:
    def payload(self):
        return {
            "models": [
                {"id": "model-a", "display_name": "Model A", "type": "text", "route_enabled": True},
                {"id": "model-b", "display_name": "Model A", "type": "text", "route_enabled": True},
                {"id": "image-a", "display_name": "Image A", "type": "image", "route_enabled": True},
                {"id": "disabled", "display_name": "Disabled", "type": "text", "route_enabled": False},
            ]
        }


class IrcBridgeServiceTests(unittest.TestCase):
    def test_parse_irc_line_handles_trailing_message(self):
        command, params = parse_irc_line("PRIVMSG #llms :hello remote client\r\n")

        self.assertEqual(command, "PRIVMSG")
        self.assertEqual(params, ["#llms", "hello remote client"])

    def test_model_directory_exposes_unique_routable_text_contacts(self):
        directory = IrcModelDirectory(FakeShowcase())
        models = directory.models()

        self.assertEqual([model["id"] for model in models], ["model-a", "model-b"])
        self.assertEqual(models[0]["irc_nick"], "Model_A")
        self.assertEqual(models[1]["irc_nick"], "Model_A_2")

    def test_metadata_log_never_persists_message_content_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "irc.jsonl"
            log = IrcMetadataLog(path)
            log.append({
                "event": "irc.chat",
                "model_id": "model-a",
                "prompt": "secret prompt",
                "message": "secret message",
                "response": "secret response",
            })
            row = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(row["model_id"], "model-a")
        self.assertNotIn("prompt", row)
        self.assertNotIn("message", row)
        self.assertNotIn("response", row)

    def test_config_store_normalizes_runtime_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "irc.json"
            metadata = Path(tmp) / "metadata.jsonl"
            store = IrcBridgeConfigStore(path=path, metadata_path=metadata)
            config = store.save({"port": 70000, "enabled": "yes", "session_name": "bad name !", "channel": "llms"})

        self.assertEqual(config["port"], 65535)
        self.assertTrue(config["enabled"])
        self.assertEqual(config["session_name"], "badname")
        self.assertEqual(config["channel"], "#llms")

    def test_text_chunks_respects_irc_line_budget(self):
        chunks = text_chunks("x" * 900, limit=200)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.encode("utf-8")) <= 200 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
