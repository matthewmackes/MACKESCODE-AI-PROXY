import datetime
import re
import unittest
from pathlib import Path

from src.console.services.agentboard import AgentBoardService


class AgentBoardServiceTests(unittest.TestCase):
    def service(self, tmux_cmd=None, logs=None, usage=None, now=1000):
        cache = {}
        logs = logs if logs is not None else []
        usage = usage or {"total_usd": 0, "by_model": []}
        calls = {"usage": []}

        def local_usage_report(start_date, end_date):
            calls["usage"].append((start_date, end_date))
            return usage

        def tail_jsonl(path, limit=80):
            return logs[-limit:]

        service = AgentBoardService(
            ansi_re=re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]"),
            permission_re=re.compile(r"allow|proceed|\\?\\s*\\[?[yY]/[nN]\\]?", re.I),
            cache=cache,
            tmux_cmd=tmux_cmd or (lambda args, check=True: (1, "", "tmux missing")),
            local_usage_report=local_usage_report,
            tail_jsonl=tail_jsonl,
            log_file=lambda: Path("/tmp/proxy.log"),
            clock=lambda: now,
        )
        return service, cache, calls

    def test_strip_ansi_and_target_sanitization(self):
        service, _, _ = self.service()
        self.assertEqual(service.strip_ansi("\x1b[31mred\x1b[0m"), "red")
        self.assertEqual(service.tmux_target(" bad name!*:0.1 "), "badname:0.1")
        self.assertEqual(service.tmux_target(""), "matts-claude")

    def test_infer_status_tracks_permission_working_and_waiting(self):
        service, cache, _ = self.service(now=1000)
        status, changed_at = service.infer_status("s:0.0", "Do you want to proceed? [y/n]", 80, 24)
        same_status, same_changed_at = service.infer_status("s:0.0", "Do you want to proceed? [y/n]", 80, 24)

        self.assertEqual(status, "permission")
        self.assertEqual(changed_at, 1000)
        self.assertEqual(same_status, "permission")
        self.assertEqual(same_changed_at, 1000)

        service_later = AgentBoardService(
            ansi_re=service.ansi_re,
            permission_re=service.permission_re,
            cache=cache,
            tmux_cmd=service.tmux_cmd,
            local_usage_report=service.local_usage_report,
            tail_jsonl=service.tail_jsonl,
            log_file=service.log_file,
            clock=lambda: 1005,
        )
        working_status, _ = service_later.infer_status("s:0.0", "new output", 80, 24)
        self.assertEqual(working_status, "working")

    def test_sessions_groups_tmux_panes_and_extracts_prompt(self):
        captures = {
            "work:0.0": "> Build the thing\nOutput",
            "work:0.1": "background pane",
            "idle:0.0": "waiting",
        }

        def tmux_cmd(args, check=True):
            if args[:2] == ["list-panes", "-a"]:
                return 0, "\n".join([
                    "work\t0\tmain\t0\tbash\t/home/project\t100\t30\t111\t1",
                    "work\t0\tmain\t1\tpython\t/home/project\tbad\tbad\t112\t0",
                    "idle\t0\tmain\t0\tbash\t/tmp\t80\t20\t113\t1",
                    "too-short",
                ]), ""
            if args[:1] == ["capture-pane"]:
                return 0, captures.get(args[-1], ""), ""
            return 1, "", "unsupported"

        service, _, _ = self.service(tmux_cmd=tmux_cmd)
        sessions, error = service.sessions()
        by_name = {item["name"]: item for item in sessions}

        self.assertEqual(error, "")
        self.assertEqual(by_name["work"]["last_prompt"], "> Build the thing")
        self.assertEqual(len(by_name["work"]["panes"]), 2)
        self.assertEqual(by_name["work"]["panes"][1]["width"], 0)
        self.assertTrue(by_name["work"]["active"])
        self.assertIn("idle", by_name)

    def test_sessions_reports_tmux_error(self):
        service, _, _ = self.service(tmux_cmd=lambda args, check=True: (1, "", "no tmux"))
        sessions, error = service.sessions()
        self.assertEqual(sessions, [])
        self.assertEqual(error, "no tmux")

    def test_usage_counts_proxy_statuses_and_uses_clock_date(self):
        logs = [{"status": 200}, {"status_code": "500"}, {"error": "bad"}, {"status": "x"}, "raw"]
        usage = {"total_usd": 3.5, "by_model": [{"model": "m", "amount_usd": 3.5}]}
        service, _, calls = self.service(logs=logs, usage=usage, now=datetime.datetime(2026, 7, 8, tzinfo=datetime.timezone.utc).timestamp())

        report, recent_logs, counts = service.usage()

        self.assertEqual(report, usage)
        self.assertEqual(recent_logs, logs)
        self.assertEqual(counts, {"ok": 1, "error": 2})
        self.assertEqual(calls["usage"][0][0].isoformat(), "2026-07-02")
        self.assertEqual(calls["usage"][0][1].isoformat(), "2026-07-08")

    def test_payload_counts_sessions_and_builds_leaderboard(self):
        def tmux_cmd(args, check=True):
            if args[:2] == ["list-panes", "-a"]:
                return 0, "work\t0\tmain\t0\tbash\t/home\t80\t20\t111\t1", ""
            if args[:1] == ["capture-pane"]:
                return 0, "task: Ship it", ""
            return 1, "", "unsupported"

        usage = {"total_usd": 1.25, "by_model": [{"model": "model-a", "amount_usd": 1.25}]}
        service, _, _ = self.service(tmux_cmd=tmux_cmd, logs=[{"status": 200}], usage=usage)
        payload = service.payload()

        self.assertEqual(payload["counts"]["waiting"], 1)
        self.assertEqual(payload["tasks"][0]["last_prompt"], "task: Ship it")
        self.assertEqual(payload["evals"]["requests_ok"], 1)
        self.assertEqual(payload["leaderboard"][0], {"name": "model-a", "score": 1.25, "metric": "local spend usd"})


if __name__ == "__main__":
    unittest.main()
