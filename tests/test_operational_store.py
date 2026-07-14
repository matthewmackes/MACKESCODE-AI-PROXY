import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.console.services.operational_store import OperationalStore
from src.console.store.base import RuntimeStateRepository


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class OperationalStoreTests(unittest.TestCase):
    def test_jsonl_backfill_parity_and_source_path_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = OperationalStore(root / "ops.sqlite3", clock=lambda: 1000)
            traces_a = root / "traces-a.jsonl"
            traces_b = root / "traces-b.jsonl"
            usage = root / "usage.jsonl"
            traces_a.write_text(
                "\n".join([
                    json.dumps({"trace_id": "t1", "timestamp": 10, "requested_model": "a"}),
                    json.dumps({"trace_id": "t2", "timestamp": 20, "requested_model": "b"}),
                ]) + "\n",
                encoding="utf-8",
            )
            traces_b.write_text(json.dumps({"trace_id": "t3", "timestamp": 30, "requested_model": "c"}) + "\n", encoding="utf-8")
            usage.write_text(
                "\n".join([
                    json.dumps({"ts": 10, "cost": {"total_cost_usd": 0.25}}),
                    json.dumps({"ts": 20, "cost": {"total_cost_usd": 0.75}}),
                ]) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(store.backfill_jsonl("traces", traces_a)["rows"], 2)
            self.assertEqual(store.backfill_jsonl("traces", traces_b)["rows"], 1)
            parity = store.parity({"usage": usage})
            rows_a = store.read_records("traces", limit=10, filters={"source_path": str(traces_a)})

        self.assertTrue(parity["sources"]["usage"]["parity"])
        self.assertEqual(parity["sources"]["usage"]["database_rows"], 2)
        self.assertEqual([row["trace_id"] for row in rows_a], ["t2", "t1"])

    def test_jsonl_backfill_keeps_duplicate_rows_and_replaces_rotated_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = OperationalStore(root / "ops.sqlite3", clock=lambda: 1000)
            usage = root / "usage.jsonl"
            usage.write_text("\n".join([
                json.dumps({"ts": 10, "cost": {"total_cost_usd": 0.25}}),
                json.dumps({"ts": 10, "cost": {"total_cost_usd": 0.25}}),
            ]) + "\n", encoding="utf-8")
            store.backfill_jsonl("usage", usage)
            first = store.read_records("usage", limit=10, filters={"source_path": str(usage)})
            usage.write_text(json.dumps({"ts": 20, "cost": {"total_cost_usd": 1.0}}) + "\n", encoding="utf-8")
            store.backfill_jsonl("usage", usage)
            second = store.read_records("usage", limit=10, filters={"source_path": str(usage)})

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["cost"]["total_cost_usd"], 1.0)

    def test_runtime_state_repository_falls_back_to_sqlite_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_file = root / "dedicated.json"
            env = {"MATTS_OPERATIONAL_DB": str(root / "ops.sqlite3")}
            with patch.dict(os.environ, env):
                repo = RuntimeStateRepository(lambda: state_file, "dedicated_state", clock=lambda: 100)
                repo.write_json({"state": "active", "secret_token": "redact-me"})
                state_file.unlink()

                restored = RuntimeStateRepository(lambda: state_file, "dedicated_state", clock=lambda: 101).read_json({})

        self.assertEqual(restored["state"], "active")
        self.assertEqual(restored["secret_token"], "redact-me")

    def test_model_registry_round_trip_preserves_order_and_route_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OperationalStore(Path(tmp) / "ops.sqlite3", clock=lambda: 100)
            store.save_model_registry(
                [
                    {"id": "zeta", "type": "text", "enabled": True},
                    {"id": "alpha", "type": "image", "enabled": False},
                ],
                route_enabled=lambda model: model.get("enabled") and model.get("type") == "text",
            )
            rows = store.load_model_registry()
            with store.connect() as conn:
                route_rows = conn.execute("SELECT model_id, route_enabled FROM model_registry ORDER BY sort_order").fetchall()

        self.assertEqual([row["id"] for row in rows], ["zeta", "alpha"])
        self.assertEqual([(row["model_id"], row["route_enabled"]) for row in route_rows], [("zeta", 1), ("alpha", 0)])

    def test_analyst_findings_track_resolution_and_acknowledgement(self):
        clock = MutableClock(100)
        with tempfile.TemporaryDirectory() as tmp:
            store = OperationalStore(Path(tmp) / "ops.sqlite3", clock=clock)
            store.save_analyst_run({
                "run_id": "r1",
                "generated_at": 100,
                "status": "ok",
                "fingerprint": "fp1",
                "proxy": {"grade": "C"},
                "summary": {"severity_counts": {"high": 1, "medium": 0, "low": 0}},
                "findings": [{"id": "f1", "fingerprint": "f1", "severity": "high", "title": "High latency"}],
            })
            clock.value = 200
            store.save_analyst_run({
                "run_id": "r2",
                "generated_at": 200,
                "status": "ok",
                "fingerprint": "fp2",
                "proxy": {"grade": "A"},
                "summary": {"severity_counts": {"high": 0, "medium": 0, "low": 0}},
                "findings": [],
            })
            acked = store.acknowledge_finding("f1", actor={"id": "operator"})
            with store.connect() as conn:
                row = conn.execute("SELECT lifecycle_status, acknowledged_at FROM analyst_findings WHERE finding_id = 'f1'").fetchone()

        self.assertEqual(row["lifecycle_status"], "resolved")
        self.assertEqual(row["acknowledged_at"], 200)
        self.assertTrue(acked["acknowledged"])
        self.assertEqual(acked["acknowledged_by"], "operator")


if __name__ == "__main__":
    unittest.main()
