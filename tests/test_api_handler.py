import unittest

from src.console.handlers.api_handler import ConsoleApiHandler


class ConsoleApiHandlerTests(unittest.TestCase):
    def handler(self):
        calls = []

        def record(name, result):
            def inner(*args, **kwargs):
                calls.append((name, args, kwargs))
                return result
            return inner

        deps = {
            "read_history": record("read_history", [{"id": "img"}]),
            "list_chats": record("list_chats", [{"id": "chat"}]),
            "load_chat": lambda chat_id: {"id": chat_id} if chat_id == "ok" else None,
            "tmux_session_items": record("tmux_session_items", [{"name": "live", "live": True}, {"name": "old", "live": False}]),
            "agentboard_payload": record("agentboard_payload", {"agents": []}),
            "models_payload": lambda refresh_catalog=True: {"models": [], "refresh_catalog": refresh_catalog},
            "sync_serverless_model_catalog": lambda **kwargs: {"ok": True, "kwargs": kwargs},
            "proxy_sync_payload": lambda **kwargs: {"in_sync": True, "kwargs": kwargs},
            "active_model_access_key_info": record("active_model_access_key_info", {"configured": True}),
            "cost_summary_payload": record("cost_summary_payload", {"cost": 1}),
            "wallpaper_payload": lambda randomize=False: {"randomize": randomize},
            "dedicated_status_payload": lambda poll=True: {"poll": poll},
            "dedicated_events": record("dedicated_events", [{"state": "ready"}]),
            "dedicated_discovery": lambda path: (207, {"path": path}),
            "proxy_get": lambda path: (200, {"path": path}),
            "port_open": lambda host, port: True,
            "proxy_host": lambda: "127.0.0.1",
            "proxy_port": lambda: 18081,
            "token_file": lambda: "/tmp/token",
            "tail_jsonl": lambda path: [{"log": str(path)}],
            "log_file": lambda: "/tmp/log",
            "tmux_sessions": record("tmux_sessions", ["one"]),
            "launcher_health": record("launcher_health", {"ok": True}),
            "generate_images": lambda data: (201, {"images": [data]}),
            "chat_completion": lambda data: (202, {"text": data["messages"][0]["content"]}),
            "save_chat": lambda data: {"saved": data},
            "delete_chat": lambda chat_id: chat_id == "chat",
            "delete_history_item": lambda image_id: image_id == "img",
            "save_models_payload": lambda data: (203, {"models": data["models"]}),
            "audit_model_access_key": record("audit_model_access_key", {"checked": 2}),
            "dedicated_preflight": lambda data: {"errors": [], "warnings": ["warn"], "config": {"id": "cfg"}},
            "append_dedicated_event": lambda *args, **kwargs: calls.append(("append_dedicated_event", args, kwargs)),
            "dedicated_build": lambda data: (204, {"built": data}),
            "dedicated_teardown": lambda data: (205, {"torn_down": data}),
            "dedicated_policy": lambda data: (206, {"policy": data}),
            "save_budget": lambda data: {"daily": data.get("daily")},
            "digitalocean_report": lambda data: {"report": data},
            "text_models": lambda: ["model-a", "model-b"],
            "default_image_model": lambda: "image-a",
            "tmux_start": lambda data: (210, {"started": data}),
            "tmux_capture": lambda name: (211, {"name": name}),
            "tmux_send_text": lambda name, text, enter: (212, {"name": name, "text": text, "enter": enter}),
            "tmux_send_key": lambda name, key: (213, {"name": name, "key": key}),
            "tmux_stop": lambda name: (214, {"name": name}),
            "tmux_rename_session": lambda old, new, display: (215, {"old": old, "new": new, "display": display}),
            "terminal_start": lambda data: (216, {"id": "term"}),
            "terminal_read": lambda session_id: (217, {"id": session_id}),
            "terminal_write": lambda session_id, text: (218, {"id": session_id, "text": text}),
            "terminal_stop": lambda session_id: (219, {"id": session_id}),
        }
        return ConsoleApiHandler(**deps), calls

    def test_get_chat_load_validation_and_tmux_sessions(self):
        handler, _ = self.handler()

        self.assertEqual(handler.get("/api/chat/load", {}), (True, 400, {"error": "id query parameter is required"}))
        self.assertEqual(handler.get("/api/chat/load", {"id": ["missing"]}), (True, 404, {"error": "chat not found"}))
        self.assertEqual(handler.get("/api/chat/load", {"id": ["ok"]}), (True, 200, {"id": "ok"}))
        handled, status, payload = handler.get("/api/tmux/sessions")

        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["sessions"], ["live"])

    def test_get_serverless_catalog_status_and_unknown(self):
        handler, _ = self.handler()
        handled, status, payload = handler.get("/api/models/serverless-catalog")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["serverless_catalog"]["ok"])
        self.assertFalse(payload["refresh_catalog"])

        handled, status, payload = handler.get("/api/status")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["proxy_listening"])
        self.assertEqual(payload["proxy"], "http://127.0.0.1:18081")
        self.assertEqual(payload["models"], {"path": "/v1/models"})

        self.assertEqual(handler.get("/not-found"), (False, 404, {}))

    def test_post_chat_dedicated_preflight_test_models_and_tmux_terminal(self):
        handler, calls = self.handler()

        self.assertEqual(handler.post("/api/chat", {"messages": [{"content": "hi"}]}), (True, 202, {"text": "hi"}))

        handled, status, payload = handler.post("/api/dedicated/preflight", {"region": "nyc"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["dedicated"], {"id": "cfg"})
        self.assertEqual(payload["events"], [{"state": "ready"}])
        self.assertTrue(any(call[0] == "append_dedicated_event" for call in calls))

        handled, status, payload = handler.post("/api/test-models", {})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual([item["model"] for item in payload["results"]], ["model-a", "model-b", "image-a"])

        self.assertEqual(handler.post("/api/tmux/send", {"name": "s", "text": "hello", "enter": True}), (True, 212, {"name": "s", "text": "hello", "enter": True}))
        self.assertEqual(handler.post("/api/terminal/read", {"id": "term"}), (True, 217, {"id": "term"}))
        self.assertEqual(handler.post("/not-found", {}), (False, 404, {}))


if __name__ == "__main__":
    unittest.main()
