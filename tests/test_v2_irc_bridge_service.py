import json
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.irc_bridge import (
    IrcBridgeConfigStore,
    IrcBridgeManager,
    IrcBridgeServer,
    IrcClientSession,
    IrcMetadataLog,
    IrcModelChat,
    IrcModelDirectory,
    compact_model_contact,
    parse_irc_line,
    tail_text,
    text_chunks,
)


class FakeShowcase:
    def payload(self):
        return {
            "models": [
                {"id": "model-a", "display_name": "Model A", "type": "text", "route_enabled": True, "artwork": {"logo": "large"}},
                {"id": "model-b", "display_name": "Model A", "type": "text", "route_enabled": True},
                {"id": "image-a", "display_name": "Image A", "type": "image", "route_enabled": True},
                {"id": "disabled", "display_name": "Disabled", "type": "text", "route_enabled": False},
            ]
        }


class LineReader:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]
        self.index = 0

    def at_eof(self):
        return self.index >= len(self.lines)

    async def readline(self):
        if self.at_eof():
            return b""
        line = self.lines[self.index]
        self.index += 1
        return line


class ResetReader:
    def at_eof(self):
        return False

    async def readline(self):
        raise ConnectionResetError("reset by peer")


class FakeWriter:
    def __init__(self):
        self.closed = False
        self.waited = False
        self.writes = []

    def get_extra_info(self, name):
        if name == "peername":
            return ("127.0.0.1", 12345)
        return None

    def write(self, _data):
        self.writes.append(_data.decode("utf-8"))

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.waited = True

    def is_closing(self):
        return self.closed


class FakeChat(IrcModelChat):
    def __init__(self):
        pass


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

    def test_status_tail_is_bounded_from_the_end(self):
        tail = tail_text("abcdefghijklmnopqrstuvwxyz", limit=24)

        self.assertTrue(tail.endswith("wxyz"))
        self.assertIn("tail truncated", tail)
        self.assertEqual(tail_text("abcdef", limit=4), "cdef")

    def test_compact_model_contact_omits_large_model_card_fields(self):
        model = IrcModelDirectory(FakeShowcase()).models()[0]
        contact = compact_model_contact(model)

        self.assertEqual(contact["id"], "model-a")
        self.assertEqual(contact["irc_nick"], "Model_A")
        self.assertNotIn("artwork", contact)

    def test_manager_status_uses_compact_model_contacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "irc.json"
            metadata = Path(tmp) / "metadata.jsonl"
            store = IrcBridgeConfigStore(path=path, metadata_path=metadata)
            manager = IrcBridgeManager(store=store, directory=IrcModelDirectory(FakeShowcase()))
            manager.has_session = lambda _session_name=None: False
            manager.listening = lambda _config=None: False

            status = manager.status()

        self.assertEqual(status["model_count"], 2)
        self.assertEqual([model["irc_nick"] for model in status["models"]], ["Model_A", "Model_A_2"])
        self.assertNotIn("artwork", status["models"][0])


class IrcBridgeServerAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_client_treats_connection_reset_as_disconnect(self):
        writer = FakeWriter()
        server = IrcBridgeServer(config={"channel": "#llms", "metadata_log": ""})

        await server.handle_client(ResetReader(), writer)

        self.assertTrue(writer.closed)
        self.assertTrue(writer.waited)

    async def test_invalid_pass_closes_session_without_processing_more_lines(self):
        writer = FakeWriter()
        session = IrcClientSession(
            reader=LineReader(["PASS wrong\r\n", "NICK should_not_apply\r\n"]),
            writer=writer,
            config={"channel": "#llms"},
            directory=IrcModelDirectory(FakeShowcase()),
            chat=FakeChat(),
            metadata_log=IrcMetadataLog(Path(tempfile.gettempdir()) / "unused-irc-test.jsonl"),
            owner_token_provider=lambda: "secret",
        )

        await session.run()

        self.assertTrue(writer.closed)
        self.assertTrue(session.closing)
        self.assertEqual(session.nick, "")


if __name__ == "__main__":
    unittest.main()
