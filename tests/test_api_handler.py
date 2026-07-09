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

        def append_trace(trace_record):
            calls.append(("append_trace", (trace_record,), {}))
            return {"trace_id": "trace-%d" % len([call for call in calls if call[0] == "append_trace"]), "status": trace_record.get("status")}

        deps = {
            "read_history": record("read_history", [{"id": "img"}]),
            "list_chats": record("list_chats", [{"id": "chat"}]),
            "load_chat": lambda chat_id: {"id": chat_id} if chat_id == "ok" else None,
            "tmux_session_items": record("tmux_session_items", [{"name": "live", "live": True}, {"name": "old", "live": False}]),
            "agentboard_payload": record("agentboard_payload", {"agents": []}),
            "plugins_payload": record("plugins_payload", {"plugins": [{"id": "plug"}]}),
            "models_payload": lambda refresh_catalog=True: {"models": [], "refresh_catalog": refresh_catalog},
            "active_auth_sessions": record("active_auth_sessions", {"sessions": [{"session_id": "session-a"}]}),
            "model_info_payload": lambda model_id=None: (200, {"model_id": model_id, "cards": []}),
            "sync_serverless_model_catalog": lambda **kwargs: {"ok": True, "kwargs": kwargs},
            "proxy_sync_payload": lambda **kwargs: {"in_sync": True, "kwargs": kwargs},
            "active_model_access_key_info": record("active_model_access_key_info", {"configured": True}),
            "cost_summary_payload": record("cost_summary_payload", {"cost": 1}),
            "read_traces": lambda **kwargs: [{"trace_id": "trace-a", "kwargs": kwargs}],
            "append_trace": append_trace,
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
            "list_eval_datasets": record("list_eval_datasets", [{"id": "smoke"}]),
            "list_eval_runs": record("list_eval_runs", [{"id": "eval-a"}]),
            "run_eval": lambda data: {"run": data},
            "save_chat": lambda data: {"id": "chat-compare", "title": data.get("title"), "messages": data.get("messages") or []},
            "delete_chat": lambda chat_id: chat_id == "chat",
            "delete_history_item": lambda image_id: image_id == "img",
            "save_models_payload": lambda data: (203, {"models": data["models"]}),
            "audit_model_access_key": record("audit_model_access_key", {"checked": 2}),
            "dedicated_preflight": lambda data: {"errors": [], "warnings": ["warn"], "config": {"id": "cfg"}},
            "append_dedicated_event": lambda *args, **kwargs: calls.append(("append_dedicated_event", args, kwargs)),
            "dedicated_build": lambda data: (204, {"built": data}),
            "dedicated_teardown": lambda data: (205, {"torn_down": data}),
            "dedicated_policy": lambda data: (206, {"policy": data}),
            "dedicated_keep_alive": lambda data: (207, {"keep_alive": data}),
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

        handled, status, payload = handler.get("/api/chat/load", {})
        self.assertTrue(handled)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "id query parameter is required")
        self.assertEqual(payload["code"], "missing_chat_id")
        self.assertEqual(payload["category"], "client")

        handled, status, payload = handler.get("/api/chat/load", {"id": ["missing"]})
        self.assertTrue(handled)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "chat not found")
        self.assertEqual(payload["code"], "chat_not_found")
        self.assertEqual(payload["details"], {"id": "missing"})
        self.assertEqual(handler.get("/api/chat/load", {"id": ["ok"]}), (True, 200, {"id": "ok"}))
        self.assertEqual(handler.get("/api/plugins"), (True, 200, {"plugins": [{"id": "plug"}]}))

    def test_get_model_info_routes(self):
        handler, _ = self.handler()

        self.assertEqual(handler.get("/api/model-info", {}), (True, 200, {"model_id": None, "cards": []}))
        self.assertEqual(handler.get("/api/model-info", {"model": ["qwen3"]}), (True, 200, {"model_id": "qwen3", "cards": []}))
        self.assertEqual(handler.get("/api/models/qwen3/info", {}), (True, 200, {"model_id": "qwen3", "cards": []}))
        handled, status, payload = handler.get("/api/tmux/sessions")

        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["sessions"], ["live"])
        self.assertEqual(handler.get("/api/auth/sessions"), (True, 200, {"sessions": [{"session_id": "session-a"}]}))

    def test_get_serverless_catalog_status_and_unknown(self):
        handler, _ = self.handler()
        handled, status, payload = handler.get("/api/models/serverless-catalog")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["serverless_catalog"]["ok"])
        self.assertFalse(payload["refresh_catalog"])
        self.assertEqual(payload["trace"]["status"], "success")

        handled, status, payload = handler.get("/api/status")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["proxy_listening"])
        self.assertEqual(payload["proxy"], "http://127.0.0.1:18081")
        self.assertEqual(payload["models"], {"path": "/v1/models"})

        handled, status, payload = handler.get("/api/traces", {"model": ["model-a"], "limit": ["5"]})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["traces"][0]["trace_id"], "trace-a")
        self.assertEqual(payload["traces"][0]["kwargs"]["model"], "model-a")
        self.assertEqual(payload["traces"][0]["kwargs"]["limit"], 5)

        handled, status, payload = handler.get("/api/evals")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["datasets"], [{"id": "smoke"}])
        self.assertEqual(payload["runs"], [{"id": "eval-a"}])

        self.assertEqual(handler.get("/not-found"), (False, 404, {}))

    def test_operator_actions_emit_traces(self):
        handler, calls = self.handler()

        actions = [
            ("/api/generate", {"model": "image-a", "prompt": "tile"}, "image.generate"),
            ("/api/model-access-audit", {}, "model_access.audit"),
            ("/api/dedicated/build", {"model_id": "dedicated-a", "provider": "digitalocean"}, "dedicated.build"),
            ("/api/dedicated/teardown", {"model_id": "dedicated-a"}, "dedicated.teardown"),
            ("/api/tmux/start", {"name": "STARTTIME_session", "model": "model-a"}, "tmux.start"),
        ]

        for path, request, expected_action in actions:
            handled, status, payload = handler.post(path, request)
            self.assertTrue(handled)
            self.assertLess(status, 400)
            self.assertIn("trace_id", payload)
            self.assertEqual(calls[-1][0], "append_trace")
            self.assertEqual(calls[-1][1][0]["action"], expected_action)

        traced_actions = [call[1][0]["action"] for call in calls if call[0] == "append_trace"]
        self.assertIn("image.generate", traced_actions)
        self.assertIn("model_access.audit", traced_actions)
        self.assertIn("dedicated.build", traced_actions)
        self.assertIn("dedicated.teardown", traced_actions)
        self.assertIn("tmux.start", traced_actions)

    def test_post_chat_dedicated_preflight_test_models_and_tmux_terminal(self):
        handler, calls = self.handler()

        self.assertEqual(handler.post("/api/chat", {"messages": [{"content": "hi"}]}), (True, 202, {"text": "hi"}))

        handled, status, payload = handler.post("/api/chat/compare", {"models": ["model-a", "model-b"], "prompt": "hi"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["models"], ["model-a", "model-b"])
        self.assertEqual(payload["chat"]["message_count"], 3)

        handled, status, payload = handler.post("/api/evals/run", {"dataset_id": "smoke"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["run"], {"dataset_id": "smoke"})

        handled, status, payload = handler.post("/api/dedicated/preflight", {"region": "nyc"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["dedicated"], {"id": "cfg"})
        self.assertEqual(payload["events"], [{"state": "ready"}])
        self.assertTrue(any(call[0] == "append_dedicated_event" for call in calls))

        handled, status, payload = handler.post("/api/dedicated/keep-alive", {"seconds": 600})
        self.assertTrue(handled)
        self.assertEqual(status, 207)
        self.assertEqual(payload["keep_alive"], {"seconds": 600})

        handled, status, payload = handler.post("/api/test-models", {})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual([item["model"] for item in payload["results"]], ["model-a", "model-b", "image-a"])

        self.assertEqual(handler.post("/api/tmux/send", {"name": "s", "text": "hello", "enter": True}), (True, 212, {"name": "s", "text": "hello", "enter": True}))
        self.assertEqual(handler.post("/api/terminal/read", {"id": "term"}), (True, 217, {"id": "term"}))
        self.assertEqual(handler.post("/not-found", {}), (False, 404, {}))

    def test_post_service_errors_are_normalized_at_api_boundary(self):
        handler, _ = self.handler()
        handler.deps["chat_completion"] = lambda data: (400, {"error": "message is required", "trace_id": "abc"})

        handled, status, payload = handler.post("/api/chat", {"messages": []})

        self.assertTrue(handled)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "message is required")
        self.assertEqual(payload["message"], "message is required")
        self.assertEqual(payload["category"], "client")
        self.assertEqual(payload["status"], 400)
        self.assertEqual(payload["trace_id"], "abc")


if __name__ == "__main__":
    unittest.main()
