import shutil
import tempfile
import unittest
from pathlib import Path

from src.console.services.session_resources import SessionResourceService


class SessionResourceServiceTests(unittest.TestCase):
    def service(self, tmux_output="", ps_output="", tmux_status=0, disk_usage=None):
        def tmux_cmd(args, check=True):
            if args[:2] == ["list-panes", "-a"]:
                return tmux_status, tmux_output, "" if tmux_status == 0 else "tmux missing"
            return 1, "", "unsupported"

        return SessionResourceService(
            tmux_cmd=tmux_cmd,
            process_runner=lambda: ps_output,
            disk_usage=disk_usage or shutil.disk_usage,
        )

    def test_summarize_aggregates_pane_process_children_without_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmux = "work\t111\t%s\tbash\nother\t999\t/tmp\tzsh" % tmp
            ps = "\n".join([
                "111 1 10.5 102400 50 bash",
                "112 111 5.0 51200 20 python",
                "113 112 1.0 1024 10 curl",
            ])
            service = self.service(tmux_output=tmux, ps_output=ps)

            summary = service.summarize("work", project_dir=tmp, idle_seconds=5)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["pane_count"], 1)
        self.assertEqual(summary["child_process_count"], 2)
        self.assertEqual(summary["cpu_percent"], 16.5)
        self.assertEqual(summary["rss_mb"], 151.0)
        self.assertEqual(summary["commands"], ["bash", "curl", "python"])
        self.assertEqual(summary["privacy"], "Process command names are reported without command arguments.")

    def test_missing_ps_and_tmux_degrade_with_errors(self):
        service = SessionResourceService(
            tmux_cmd=lambda args, check=True: (1, "", "no tmux"),
            process_runner=lambda: (_ for _ in ()).throw(RuntimeError("no ps")),
            disk_usage=lambda path: (_ for _ in ()).throw(RuntimeError("no disk")),
        )

        summary = service.summarize("work", project_dir="/missing")

        self.assertFalse(summary["available"])
        self.assertIn("no tmux", summary["errors"])
        self.assertIn("no ps", summary["errors"])
        self.assertIn("no disk", summary["errors"])

    def test_warning_thresholds_cover_cpu_memory_idle_disk_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "build").mkdir()
            (root / "build" / "artifact.bin").write_bytes(b"x" * 1024)

            usage = shutil._ntuple_diskusage(total=1000, used=950, free=50)
            service = self.service(
                tmux_output="work\t111\t%s\tbash" % tmp,
                ps_output="111 1 300 3145728 50 bash",
                disk_usage=lambda path: usage,
            )
            summary = service.summarize("work", project_dir=tmp, idle_seconds=5 * 3600)
            summary["disk"]["artifact_mb"] = 600
            warnings = service.warnings(summary, idle_seconds=5 * 3600)

        codes = [item["code"] for item in warnings]
        self.assertIn("runaway_cpu", codes)
        self.assertIn("high_memory", codes)
        self.assertIn("stale_session", codes)
        self.assertIn("low_disk_space", codes)
        self.assertIn("large_artifacts", codes)


if __name__ == "__main__":
    unittest.main()
