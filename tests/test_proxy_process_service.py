import tempfile
import unittest
from pathlib import Path

from src.console.services.proxy_process import ProxyProcessService


class ProxyProcessServiceTests(unittest.TestCase):
    def service(self, tmp, **overrides):
        root = Path(tmp)
        fingerprint = {"path": str(root / "models.json"), "exists": True, "mtime_ns": 1, "size": 2}
        records = {"requests": [], "runs": [], "popen": [], "kills": [], "sleeps": [], "wrote_token": 0}

        def request_json(url, payload=None, timeout=240, method="POST"):
            records["requests"].append((url, payload, timeout, method))
            return 200, {"ok": True}

        kwargs = {
            "proxy_host": lambda: "127.0.0.1",
            "proxy_port": lambda: 18081,
            "port_open": lambda host, port: True,
            "request_json": request_json,
            "proxy_capabilities_raw": lambda: (200, {
                "provider": "matts-value-set",
                "base_url": "https://inference.do-ai.run",
                "models": ["model-a"],
                "model_config_state": {"loaded": True, "stale": False, "fingerprint": fingerprint},
            }),
            "model_config_fingerprint": lambda: fingerprint,
            "same_model_config_fingerprint": lambda left, right: left == right,
            "all_models": lambda: ["model-a"],
            "base_url": lambda: "https://inference.do-ai.run",
            "write_token": lambda: records.__setitem__("wrote_token", records["wrote_token"] + 1),
            "default_text_model": lambda: "model-a",
            "token_file": lambda: root / "token",
            "model_config_file": lambda: root / "models.json",
            "cost_file": lambda: root / "usage.jsonl",
            "budget_file": lambda: root / "budgets.json",
            "log_file": lambda: root / "proxy.jsonl",
            "trace_file": lambda: root / "traces.jsonl",
            "proxy_script": lambda: root / "do-anthropic-proxy.py",
            "executable": "/python",
            "env": {},
            "run_func": lambda args, **kwargs: records["runs"].append((args, kwargs)),
            "check_output_func": lambda args, **kwargs: "",
            "popen_func": lambda args, **kwargs: records["popen"].append((args, kwargs)),
            "kill_func": lambda pid, sig: records["kills"].append((pid, sig)),
            "sleep_func": lambda seconds: records["sleeps"].append(seconds),
            "devnull": object(),
        }
        kwargs.update(overrides)
        return ProxyProcessService(**kwargs), records, fingerprint

    def test_in_sync_requires_matching_capabilities_and_registry_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _ = self.service(tmp)
            ok, details = service.in_sync()

        self.assertTrue(ok)
        self.assertEqual(details["reason"], "in sync")
        self.assertEqual(details["expected_models"], ["model-a"])

    def test_in_sync_reports_not_listening_stale_and_registry_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            not_listening, _, _ = self.service(tmp, port_open=lambda host, port: False)
            not_listening_ok, not_listening_details = not_listening.in_sync()

        stale_payload = {
            "provider": "matts-value-set",
            "base_url": "https://inference.do-ai.run",
            "models": ["model-a"],
            "model_config_state": {"loaded": True, "stale": True, "fingerprint": {}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            stale, _, _ = self.service(tmp, proxy_capabilities_raw=lambda: (200, stale_payload))
            stale_ok, stale_details = stale.in_sync()

        error_payload = {
            "provider": "matts-value-set",
            "base_url": "https://inference.do-ai.run",
            "models": ["model-a"],
            "model_config_state": {"loaded": False, "last_error": "bad registry"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            errored, _, _ = self.service(tmp, proxy_capabilities_raw=lambda: (200, error_payload))
            error_ok, error_details = errored.in_sync()

        self.assertFalse(not_listening_ok)
        self.assertEqual(not_listening_details["reason"], "proxy is not listening")
        self.assertFalse(stale_ok)
        self.assertIn("not reloaded", stale_details["reason"])
        self.assertFalse(error_ok)
        self.assertIn("bad registry", error_details["reason"])

    def test_force_start_uses_reload_when_proxy_becomes_in_sync(self):
        states = [
            {"loaded": True, "stale": True, "fingerprint": {}},
            {"loaded": True, "stale": False, "fingerprint": {"path": "x", "exists": True, "mtime_ns": 1, "size": 2}},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            service, records, fingerprint = self.service(
                tmp,
                proxy_capabilities_raw=lambda: (200, {
                    "provider": "matts-value-set",
                    "base_url": "https://inference.do-ai.run",
                    "models": ["model-a"],
                    "model_config_state": states.pop(0),
                }),
                model_config_fingerprint=lambda: fingerprint,
                same_model_config_fingerprint=lambda left, right: True,
            )
            service.start_if_needed(force=True)

        self.assertEqual(records["wrote_token"], 0)
        self.assertEqual(records["popen"], [])
        self.assertTrue(any(item[0].endswith("/v1/claude-do/reload") for item in records["requests"]))

    def test_start_launches_proxy_when_not_listening(self):
        open_checks = [False, False, True]

        def port_open(host, port):
            return open_checks.pop(0) if open_checks else True

        with tempfile.TemporaryDirectory() as tmp:
            service, records, _ = self.service(tmp, port_open=port_open)
            service.start_if_needed()

        self.assertEqual(records["wrote_token"], 1)
        self.assertEqual(len(records["popen"]), 1)
        command = records["popen"][0][0]
        self.assertIn("--provider", command)
        self.assertIn("--models", command)
        self.assertIn("--trace-file", command)
        self.assertIn(str(Path(tmp) / "traces.jsonl"), command)

    def test_stop_kills_tmux_and_listener_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, records, _ = self.service(
                tmp,
                check_output_func=lambda args, **kwargs: "123\nbad\n",
                env={"MATTS_VALUE_SET_TMUX_SESSION": "proxy-tmux"},
            )
            service.stop()

        self.assertEqual(records["runs"][0][0], ["tmux", "kill-session", "-t", "proxy-tmux"])
        self.assertEqual(records["kills"][0][0], 123)
        self.assertEqual(records["sleeps"], [0.4])

    def test_sync_payload_includes_start_error_and_registry_issue_respects_loaded_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _ = self.service(
                tmp,
                proxy_in_sync_func=lambda: (False, {
                    "reason": "stale",
                    "expected_models": ["new-model"],
                    "capabilities": {"models": ["loaded-model"], "model_config_state": {"stale": True}},
                    "expected_model_config": {"exists": True},
                }),
            )
            loaded_issue = service.registry_sync_issue_for_model("loaded-model")
            missing_issue = service.registry_sync_issue_for_model("new-model")

        self.assertFalse(loaded_issue["blocking"])
        self.assertTrue(loaded_issue["selected_model_loaded"])
        self.assertTrue(missing_issue["blocking"])
        self.assertFalse(missing_issue["selected_model_loaded"])


if __name__ == "__main__":
    unittest.main()
