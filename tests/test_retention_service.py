import gzip
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src.console.services.retention import DEFAULT_KEEP_BYTES, DEFAULT_MAX_BYTES, RetentionService
from src.console.services.usage import UsageService, _TTLCache

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_780_000_000.0


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


class RetentionRotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.service = RetentionService(env={})

    def test_no_rotation_at_or_below_threshold(self):
        path = self.dir / "usage.jsonl"
        write_lines(path, [json.dumps({"i": i}) for i in range(10)])
        original = path.read_bytes()

        result = self.service.rotate_if_needed(path, max_bytes=len(original), keep_bytes=64)

        self.assertFalse(result["rotated"])
        self.assertEqual(result["reason"], "under_threshold")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(RetentionService.archive_path(path).exists())

    def test_rotate_missing_file_is_noop(self):
        path = self.dir / "missing.jsonl"

        result = self.service.rotate_if_needed(path, max_bytes=100, keep_bytes=10)

        self.assertEqual(result, {"path": str(path), "rotated": False, "reason": "missing"})
        self.assertFalse(path.exists())
        self.assertFalse(RetentionService.archive_path(path).exists())

    def test_rotation_keeps_line_aligned_tail_within_keep_bytes(self):
        path = self.dir / "traces.jsonl"
        write_lines(path, [json.dumps({"i": i, "pad": "p" * 40}) for i in range(500)])
        os.chmod(path, 0o600)
        original = path.read_bytes()

        result = self.service.rotate_if_needed(path, max_bytes=8000, keep_bytes=2000)

        kept = path.read_bytes()
        self.assertTrue(result["rotated"])
        self.assertEqual(result["kept_bytes"], len(kept))
        self.assertLessEqual(len(kept), 2000)
        self.assertGreater(len(kept), 0)
        # Kept content is a byte-exact suffix of the original that starts on a
        # line boundary, so every retained line is a complete original row.
        self.assertTrue(original.endswith(kept))
        self.assertEqual(original[len(original) - len(kept) - 1:len(original) - len(kept)], b"\n")
        for line in kept.decode("utf-8").splitlines():
            json.loads(line)
        # Atomic replace preserves the live file's permissions.
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_archive_contains_trimmed_head_and_is_single_generation(self):
        path = self.dir / "usage.jsonl"
        write_lines(path, [json.dumps({"gen": 1, "i": i, "pad": "a" * 30}) for i in range(300)])
        first = path.read_bytes()
        archive = RetentionService.archive_path(path)
        self.assertEqual(archive.name, "usage.1.jsonl.gz")

        result = self.service.rotate_if_needed(path, max_bytes=4000, keep_bytes=1000)

        self.assertTrue(result["rotated"])
        self.assertEqual(result["archive"], str(archive))
        # Archive head + kept tail reconstruct the original file exactly.
        self.assertEqual(gzip.decompress(archive.read_bytes()) + path.read_bytes(), first)

        # A later rotation overwrites the single-generation archive rather
        # than accumulating: the archive then holds only the second head.
        with path.open("a", encoding="utf-8") as handle:
            for i in range(300):
                handle.write(json.dumps({"gen": 2, "i": i, "pad": "b" * 30}) + "\n")
        second = path.read_bytes()

        result = self.service.rotate_if_needed(path, max_bytes=4000, keep_bytes=1000)

        self.assertTrue(result["rotated"])
        self.assertEqual(gzip.decompress(archive.read_bytes()) + path.read_bytes(), second)
        self.assertEqual(list(path.parent.glob("*.gz")), [archive])

    def test_rotation_triggers_only_over_max_bytes(self):
        path = self.dir / "log.jsonl"
        write_lines(path, [json.dumps({"i": i}) for i in range(50)])
        size = path.stat().st_size

        self.assertFalse(self.service.rotate_if_needed(path, max_bytes=size, keep_bytes=64)["rotated"])
        self.assertTrue(self.service.rotate_if_needed(path, max_bytes=size - 1, keep_bytes=64)["rotated"])


class RetentionMaintainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_maintain_throttles_between_sweeps(self):
        path = self.dir / "usage.jsonl"
        write_lines(path, [json.dumps({"i": i}) for i in range(5)])
        clock = MutableClock(NOW)
        service = RetentionService(targets=[lambda: path], sweep_interval=600, clock=clock, env={})

        first = service.maintain()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["reason"], "under_threshold")

        clock.value += 30
        self.assertEqual(service.maintain(), [])
        self.assertEqual(len(service.maintain(force=True)), 1)

        clock.value += 600
        self.assertEqual(len(service.maintain()), 1)

    def test_maintain_survives_failing_target(self):
        path = self.dir / "traces.jsonl"
        write_lines(path, [json.dumps({"i": i, "pad": "x" * 40}) for i in range(200)])

        def bad_target():
            raise RuntimeError("boom")

        service = RetentionService(targets=[bad_target, lambda: path], max_bytes=1000, keep_bytes=200, env={})
        results = service.maintain()

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], {"path": None, "rotated": False, "error": "boom"})
        self.assertTrue(results[1]["rotated"])
        self.assertLessEqual(path.stat().st_size, 200)

    def test_env_overrides_and_clamping(self):
        service = RetentionService(env={"MATTS_RETENTION_MAX_BYTES": "1000", "MATTS_RETENTION_KEEP_BYTES": "200"})
        self.assertEqual(service.max_bytes, 1000)
        self.assertEqual(service.keep_bytes, 200)

        service = RetentionService(env={"MATTS_RETENTION_MAX_BYTES": "nope", "MATTS_RETENTION_KEEP_BYTES": "-5"})
        self.assertEqual(service.max_bytes, DEFAULT_MAX_BYTES)
        self.assertEqual(service.keep_bytes, DEFAULT_KEEP_BYTES)

        # A keep window >= the trigger threshold would rotate every sweep.
        service = RetentionService(max_bytes=1000, keep_bytes=5000, env={})
        self.assertEqual(service.keep_bytes, 250)


class RetentionUsageCorrectnessTests(unittest.TestCase):
    """Budget/analytics reads key caches on (mtime, size); rotation must
    invalidate them naturally and keep recent-window totals correct."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def usage_service(self, cost_path):
        def tail_jsonl(path, limit=80):
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                rows.append(json.loads(line))
            return rows

        return UsageService(
            cost_file=lambda: cost_path,
            budget_file=lambda: self.dir / "budget.json",
            tail_jsonl=tail_jsonl,
            do_get=lambda path, token, query=None, timeout=30: (200, {}),
            digitalocean_token=lambda: "",
            digitalocean_account_urn=lambda: "",
            digitalocean_health_snapshot=lambda: {"account": {}, "prepay": {}, "errors": []},
            load_dedicated_config=lambda: {},
            dedicated_runtime_cost_summary=lambda cfg, now: {"month_cost_usd": 0.0, "last_24h_cost_usd": 0.0},
            clock=lambda: NOW,
            insights_cache=_TTLCache(),
            usage_rows_cache=_TTLCache(),
        )

    def test_recent_totals_survive_rotation(self):
        cost_path = self.dir / "usage.jsonl"
        old_rows = [json.dumps({"ts": NOW - 8 * 86400, "requested_model": "m", "cost": {"total_cost_usd": 0.5}, "pad": "x" * 30}) for _ in range(200)]
        recent_rows = [json.dumps({"ts": NOW - 3600, "requested_model": "m", "cost": {"total_cost_usd": 0.25}}) for _ in range(20)]
        write_lines(cost_path, old_rows + recent_rows)
        recent_block = sum(len(row.encode("utf-8")) + 1 for row in recent_rows)
        service = self.usage_service(cost_path)

        before = service.local_usage_since(NOW - 86400, NOW)
        self.assertEqual(before, 5.0)

        # Keep slightly more than the recent block: the window starts inside
        # the final old row, and line alignment drops that partial row.
        retention = RetentionService(env={})
        result = retention.rotate_if_needed(cost_path, max_bytes=recent_block, keep_bytes=recent_block + 10)

        self.assertTrue(result["rotated"])
        self.assertEqual(result["kept_bytes"], recent_block)
        # Recent-window totals are identical across the rotation boundary even
        # though the same UsageService instance (and its mtime/size-keyed row
        # cache) served both reads.
        self.assertEqual(service.local_usage_since(NOW - 86400, NOW), before)
        # The trimmed history is out of the live file but preserved in the archive.
        self.assertEqual(service.local_usage_since(NOW - 30 * 86400, NOW), 5.0)
        archived = gzip.decompress(RetentionService.archive_path(cost_path).read_bytes())
        self.assertEqual(archived.decode("utf-8").splitlines(), old_rows)


class RetentionProxyBudgetTests(unittest.TestCase):
    """Budget enforcement lives in the proxy's incremental `_UsageAggregator`;
    `os.replace` rotation changes the file's inode, which must trigger its
    documented reset-and-reseed path without breaking daily budget checks."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("do_anthropic_proxy_retention", ROOT / "do-anthropic-proxy.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.proxy = module

    def test_budget_aggregator_and_daily_limit_survive_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cost_path = Path(tmp) / "usage.jsonl"
            budget_path = Path(tmp) / "budgets.json"
            budget_path.write_text(json.dumps({"daily_usd": 4.0}), encoding="utf-8")
            now = time.time()
            old_rows = [json.dumps({"ts": now - 8 * 86400, "cost": {"total_cost_usd": 0.5}, "pad": "x" * 30}) for _ in range(200)]
            today_rows = [json.dumps({"ts": now, "cost": {"total_cost_usd": 0.25}}) for _ in range(20)]
            write_lines(cost_path, old_rows + today_rows)
            today_block = sum(len(row.encode("utf-8")) + 1 for row in today_rows)

            aggregator = self.proxy._UsageAggregator()
            self.assertAlmostEqual(aggregator.totals(str(cost_path))["today"], 5.0)
            self.assertIsNotNone(self.proxy._budget_error(str(cost_path), str(budget_path), aggregator))

            result = RetentionService(env={}).rotate_if_needed(cost_path, max_bytes=today_block, keep_bytes=today_block + 10)
            self.assertTrue(result["rotated"])

            totals = aggregator.totals(str(cost_path))
            self.assertAlmostEqual(totals["today"], 5.0)
            # Documented tradeoff: after re-seeding from the rotated file, the
            # all-time bucket reflects only the retained window.
            self.assertAlmostEqual(totals["all"], 5.0)
            error = self.proxy._budget_error(str(cost_path), str(budget_path), aggregator)
            self.assertIsNotNone(error)
            self.assertEqual(error["type"], "budget_exceeded")


if __name__ == "__main__":
    unittest.main()
