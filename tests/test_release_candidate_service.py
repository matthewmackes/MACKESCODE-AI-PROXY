import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.release_candidate import ReleaseCandidateService


class ReleaseCandidateServiceTests(unittest.TestCase):
    def service(self, root, *, coverage=True, drift=None, reviews=None, traces=None, eval_runs=None, worklist_text=None, needs_text=None, requirements_text=None):
        root = Path(root)
        coverage_file = root / "build" / "coverage" / "coverage.json"
        if coverage:
            coverage_file.parent.mkdir(parents=True)
            coverage_file.write_text(json.dumps({"summary": {"coverage_percent": 47.5, "covered_lines": 10, "measured_lines": 21}}), encoding="utf-8")
        worklist = root / "MAIN-WORKLIST.md"
        worklist.write_text(worklist_text or "### Task ID: INT-001\n**Status:** ✅ `COMPLETED`\n**Priority:** P1\n", encoding="utf-8")
        needs = root / "docs" / "NEEDS-OPERATOR.md"
        needs.parent.mkdir(parents=True, exist_ok=True)
        needs.write_text(needs_text if needs_text is not None else "| Item | Needs | Status |\n| --- | --- | --- |\n| One | Operator | Open |\n", encoding="utf-8")
        requirements = root / "docs" / "requirements-ledger.md"
        requirements.write_text(
            requirements_text if requirements_text is not None else "# Requirements Ledger\n\n## Priority Order\n\nNo code-owned priority work is open.\n",
            encoding="utf-8",
        )
        for doc in ("GOVERNANCE.md", "RELEASE.md", "SECURITY.md", "CHANGELOG.md"):
            (root / doc).write_text(doc, encoding="utf-8")
        return ReleaseCandidateService(
            reports_dir=lambda: root / "reports",
            coverage_file=lambda: coverage_file,
            worklist_file=lambda: worklist,
            needs_operator_file=lambda: needs,
            config_drift_payload=lambda: drift or {"summary": {"state": "clean", "active_drift_count": 0}, "drift": []},
            review_queue_payload=lambda **kwargs: {"reviews": reviews or []},
            read_traces=lambda **kwargs: traces or [],
            list_eval_runs=lambda limit=10: eval_runs or [],
            clock=lambda: 1000,
        )

    def test_payload_passes_when_blocking_checks_are_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp).payload()

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["summary"]["blocking_failed"], 0)
        needs_check = next(check for check in payload["checks"] if check["id"] == "needs_operator")
        self.assertEqual(needs_check["severity"], "advisory")
        self.assertEqual(needs_check["status"], "failed")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["summary"]["advisory_failed"], 1)

    def test_missing_artifacts_drift_reviews_traces_and_evals_block_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(
                tmp,
                coverage=False,
                drift={"summary": {"state": "drift", "active_drift_count": 1}, "drift": [{"name": "model_registry"}]},
                reviews=[{"id": "r1", "status": "open", "severity": "high"}],
                traces=[{"trace_id": "t1", "timestamp": 999, "status": "error"}],
                eval_runs=[{"id": "eval1", "summary": [{"model": "m", "failures": 1}]}],
            ).payload()
            failed = {check["id"] for check in payload["checks"] if check["status"] == "failed"}

        self.assertFalse(payload["ready"])
        self.assertIn("release_check_artifacts", failed)
        self.assertIn("coverage", failed)
        self.assertIn("config_drift", failed)
        self.assertIn("open_reviews", failed)
        self.assertIn("recent_failed_traces", failed)
        self.assertIn("eval_failures", failed)

    def test_config_drift_missing_baseline_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(
                tmp,
                drift={
                    "summary": {"state": "no_baseline", "baseline_present": False, "active_drift_count": 1, "highest_risk": "low"},
                    "drift": [{"name": "tmux_registry", "risk": "low", "changed": True, "acknowledged": False}],
                },
            ).payload()
            check = next(check for check in payload["checks"] if check["id"] == "config_drift")

        self.assertFalse(payload["ready"])
        self.assertEqual(check["status"], "failed")
        self.assertTrue(check["blocking"])
        self.assertEqual(check["severity"], "blocking")

    def test_low_risk_config_drift_is_advisory_not_release_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(
                tmp,
                drift={
                    "summary": {"state": "drift", "baseline_present": True, "active_drift_count": 1, "highest_risk": "low"},
                    "drift": [{"name": "tmux_registry", "risk": "low", "changed": True, "acknowledged": False}],
                },
            ).payload()
            check = next(check for check in payload["checks"] if check["id"] == "config_drift")

        self.assertTrue(payload["ready"])
        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["blocking"])
        self.assertEqual(check["severity"], "advisory")
        self.assertEqual(check["evidence"]["active_drift_count"], 1)
        self.assertEqual(check["evidence"]["blocking_drift_count"], 0)
        self.assertEqual(check["evidence"]["advisory_drift_count"], 1)
        self.assertEqual(check["evidence"]["advisory_drift"][0]["name"], "tmux_registry")

    def test_medium_or_high_config_drift_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(
                tmp,
                drift={
                    "summary": {"state": "drift", "baseline_present": True, "active_drift_count": 2, "highest_risk": "high"},
                    "drift": [
                        {"name": "tmux_registry", "risk": "low", "changed": True, "acknowledged": False},
                        {"name": "model_registry", "risk": "high", "changed": True, "acknowledged": False},
                    ],
                },
            ).payload()
            check = next(check for check in payload["checks"] if check["id"] == "config_drift")

        self.assertFalse(payload["ready"])
        self.assertEqual(check["status"], "failed")
        self.assertTrue(check["blocking"])
        self.assertEqual(check["severity"], "blocking")
        self.assertEqual(check["evidence"]["active_drift_count"], 2)
        self.assertEqual(check["evidence"]["blocking_drift_count"], 1)
        self.assertEqual(check["evidence"]["advisory_drift_count"], 1)
        self.assertEqual(check["evidence"]["blocking_drift"][0]["name"], "model_registry")

    def test_write_report_persists_runtime_safe_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.service(tmp).write_report({"label": "rc1"})
            path = Path(report["report_file"])
            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(report["label"], "rc1")
        self.assertEqual(stored["label"], "rc1")
        self.assertIn("operator_handoff", stored)
        self.assertTrue(path.name.startswith("release-candidate-"))

    def test_needs_operator_check_passes_when_no_open_rows(self):
        needs_text = "| Item | Needs | Status |\n| --- | --- | --- |\n"
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, needs_text=needs_text).needs_operator_check()

        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["evidence"]["open_items"], 0)
        self.assertEqual(check["evidence"]["items"], [])

    def test_needs_operator_check_fails_advisory_for_open_rows(self):
        needs_text = "| Item | Needs | Status |\n| --- | --- | --- |\n| One | Operator | Open |\n| Two | Account | Waiting |\n"
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, needs_text=needs_text).needs_operator_check()

        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["blocking"])
        self.assertEqual(check["severity"], "advisory")
        self.assertEqual(check["evidence"]["open_items"], 2)
        self.assertEqual(len(check["evidence"]["items"]), 2)

    def test_needs_operator_check_ignores_resolved_rows(self):
        needs_text = "\n".join([
            "| Item | Needs | Status |",
            "| --- | --- | --- |",
            "| One | Operator | Closed 2026-07-11: evidence recorded. |",
            "| Two | Product | Canceled 2026-07-11: operator retired the work. |",
            "| Three | Release | Resolved 2026-07-11: policy recorded. |",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp, needs_text=needs_text).payload()

        needs_check = next(check for check in payload["checks"] if check["id"] == "needs_operator")
        self.assertEqual(needs_check["status"], "passed")
        self.assertEqual(needs_check["evidence"]["open_items"], 0)
        self.assertEqual(payload["operator_handoff"]["open_count"], 0)

    def test_operator_handoff_structures_open_needs_operator_rows(self):
        needs_text = "| Item | Needs | Status |\n| --- | --- | --- |\n| Dedicated capacity | GPU capacity | Operator/live-cloud gated |\n| Release policy | Version decision | Open |\n"
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp, needs_text=needs_text).payload()

        handoff = payload["operator_handoff"]
        self.assertFalse(handoff["blocking"])
        self.assertEqual(handoff["open_count"], 2)
        self.assertIn("2 operator-owned release items", handoff["summary"])
        self.assertEqual(handoff["items"][0]["item"], "Dedicated capacity")
        self.assertEqual(handoff["items"][0]["needs"], "GPU capacity")
        self.assertEqual(handoff["items"][0]["status"], "Operator/live-cloud gated")
        self.assertEqual(handoff["items"][0]["gate_type"], "live-cloud")
        self.assertEqual(handoff["items"][0]["owner"], "Cloud operator")
        self.assertIn("DigitalOcean", handoff["items"][0]["next_action"])
        self.assertIn("timestamp", handoff["items"][0]["evidence_required"])
        self.assertIn("Status cell: Closed <YYYY-MM-DD>", handoff["items"][0]["closure_template"])
        self.assertIn("Owner: Cloud operator", handoff["items"][0]["closure_template"])
        self.assertIn("Gate: live-cloud", handoff["items"][0]["closure_template"])
        self.assertEqual(handoff["items"][0]["priority_rank"], 1)
        self.assertEqual(handoff["items"][0]["urgency"], "highest")
        self.assertIn("Cloud capacity", handoff["items"][0]["blocking_rationale"])
        self.assertIn("needs_operator", handoff["advisory_failed_checks"])

    def test_operator_handoff_plans_cover_known_gate_types(self):
        needs_text = "\n".join([
            "| Item | Needs | Status |",
            "| --- | --- | --- |",
            "| DigitalOcean billing and prepay completeness | Token/account with billing visibility | Waiting |",
            "| Final public release/version policy | semantic version and tag process | Open |",
            "| GitHub repository administration | branch protection and required checks | Operator-owned |",
            "| Unrecoverable survey answer mappings | Original prompts for compacted answers | Waiting |",
            "| Other signoff | Manual operator decision | Open |",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            handoff = self.service(tmp, needs_text=needs_text).payload()["operator_handoff"]

        gate_types = [item["gate_type"] for item in handoff["items"]]
        self.assertEqual(gate_types, ["account-billing", "release-policy", "repository-admin", "product-decision", "operator-decision"])
        self.assertIn("prepaid balance", handoff["items"][0]["evidence_required"])
        self.assertIn("semantic version", handoff["items"][1]["evidence_required"])
        self.assertIn("branch protection", handoff["items"][2]["next_action"])
        self.assertIn("Restate", handoff["items"][3]["next_action"])
        self.assertIn("updated status", handoff["items"][4]["evidence_required"])
        self.assertTrue(all("closure_template" in item for item in handoff["items"]))
        self.assertIn("Gate: repository-admin", handoff["items"][2]["closure_template"])
        self.assertIn("Owner: Product owner", handoff["items"][3]["closure_template"])
        self.assertEqual([item["priority_rank"] for item in handoff["items"]], [1, 2, 3, 4, 5])
        self.assertEqual([item["urgency"] for item in handoff["items"]], ["high", "high", "medium", "medium", "normal"])
        self.assertTrue(all("blocking_rationale" in item for item in handoff["items"]))

    def test_operator_handoff_prioritizes_capacity_before_later_ledger_rows(self):
        needs_text = "\n".join([
            "| Item | Needs | Status |",
            "| --- | --- | --- |",
            "| GitHub repository administration | branch protection and required checks | Operator-owned |",
            "| Dedicated Inference live capacity verification | DigitalOcean GPU capacity | Operator/live-cloud gated |",
            "| DigitalOcean billing and prepay completeness | account billing visibility | Waiting |",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            handoff = self.service(tmp, needs_text=needs_text).payload()["operator_handoff"]

        self.assertEqual([item["gate_type"] for item in handoff["items"]], ["live-cloud", "account-billing", "repository-admin"])
        self.assertEqual([item["priority_rank"] for item in handoff["items"]], [1, 2, 3])
        self.assertEqual(handoff["items"][0]["original_index"], 1)

    def test_operator_handoff_empty_when_operator_ledger_has_no_rows(self):
        needs_text = "| Item | Needs | Status |\n| --- | --- | --- |\n"
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp, needs_text=needs_text).payload()

        handoff = payload["operator_handoff"]
        self.assertEqual(handoff["open_count"], 0)
        self.assertEqual(handoff["items"], [])
        self.assertEqual(handoff["summary"], "No operator-owned release items are open.")

    def test_worklist_check_detects_open_priority_work_regardless_field_order(self):
        worklist = """
### Task ID: INT-001
**Title:** Canonical order
**Status:** 📋 `TODO`
**Priority:** P1

### Task ID: INT-002
**Title:** Reversed order
**Priority:** P1
**Status:** 🔄 `IN_PROGRESS`

### Task ID: INT-003
**Title:** Completed release work
**Status:** ✅ `COMPLETED`
**Priority:** P1

### Task ID: INT-004
**Title:** Cancelled release work
**Priority:** P0
**Status:** ❌ `CANCELLED`

### Task ID: INT-005
**Title:** Lower priority backlog
**Status:** 📋 `TODO`
**Priority:** P2
"""
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, worklist_text=worklist).worklist_check()

        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["blocking"])
        self.assertEqual(check["evidence"]["pending_p1_estimate"], 2)
        self.assertEqual([item["id"] for item in check["evidence"]["pending_items"]], ["INT-001", "INT-002"])
        self.assertEqual(check["evidence"]["duplicate_task_ids"], [])

    def test_worklist_check_detects_duplicate_task_ids_even_when_completed(self):
        worklist = """
### Task ID: INT-001
**Title:** First completed task
**Status:** ✅ `COMPLETED`
**Priority:** P1

### Task ID: INT-001
**Title:** Second completed task
**Status:** ✅ `COMPLETED`
**Priority:** P2
"""
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, worklist_text=worklist).worklist_check()

        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["blocking"])
        self.assertEqual(check["evidence"]["pending_p1_estimate"], 0)
        self.assertEqual(check["evidence"]["duplicate_task_count"], 1)
        duplicate = check["evidence"]["duplicate_task_ids"][0]
        self.assertEqual(duplicate["id"], "INT-001")
        self.assertEqual(duplicate["count"], 2)
        self.assertEqual([task["title"] for task in duplicate["tasks"]], ["First completed task", "Second completed task"])
        self.assertEqual([task["line"] for task in duplicate["tasks"]], [2, 7])

    def test_worklist_check_ignores_fenced_task_examples(self):
        worklist = """
### Task ID: INT-001
**Title:** Completed release work
**Status:** ✅ `COMPLETED`
**Priority:** P1

```
### Task ID: INT-001
**Title:** Example only
**Status:** 📋 `TODO`
**Priority:** P1
```
"""
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, worklist_text=worklist).worklist_check()

        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["evidence"]["pending_p1_estimate"], 0)
        self.assertEqual(check["evidence"]["duplicate_task_ids"], [])

    def test_worklist_check_passes_when_priority_work_is_completed_or_cancelled(self):
        worklist = """
### Task ID: INT-001
**Title:** Completed release work
**Status:** ✅ `COMPLETED`
**Priority:** P1

### Task ID: INT-002
**Title:** Cancelled release work
**Priority:** P0
**Status:** ❌ `CANCELLED`
"""
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, worklist_text=worklist).worklist_check()

        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["evidence"]["pending_p1_estimate"], 0)
        self.assertEqual(check["evidence"]["pending_items"], [])
        self.assertEqual(check["evidence"]["duplicate_task_ids"], [])

    def test_requirements_ledger_check_flags_completed_priority_rows(self):
        worklist = """
### Task ID: INT-014
**Title:** Completed Create work
**Status:** ✅ `COMPLETED`
**Priority:** P1

### Task ID: INT-200
**Title:** Active follow-up
**Status:** 📋 `TODO`
**Priority:** P2
"""
        requirements = """
# Requirements Ledger

## Priority Order

1. `INT-014` finish the remaining Create work.
2. `INT-200` continue later polish.
"""
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, worklist_text=worklist, requirements_text=requirements).requirements_ledger_check()

        self.assertEqual(check["status"], "failed")
        self.assertFalse(check["blocking"])
        self.assertEqual(check["severity"], "advisory")
        self.assertEqual(check["evidence"]["priority_item_count"], 2)
        self.assertEqual(check["evidence"]["stale_completed_priority_count"], 1)
        stale = check["evidence"]["stale_completed_priorities"][0]
        self.assertEqual(stale["task_ids"], ["INT-014"])
        self.assertEqual(stale["completed_tasks"][0]["status"], "COMPLETED")

    def test_requirements_ledger_check_passes_current_policy_without_numbered_completed_tasks(self):
        worklist = """
### Task ID: INT-014
**Title:** Completed Create work
**Status:** ✅ `COMPLETED`
**Priority:** P1
"""
        requirements = """
# Requirements Ledger

## Priority Order

No code-owned priority work is open. Continue audit-driven polish through new worklist items.
"""
        with tempfile.TemporaryDirectory() as tmp:
            check = self.service(tmp, worklist_text=worklist, requirements_text=requirements).requirements_ledger_check()

        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["evidence"]["priority_item_count"], 0)
        self.assertEqual(check["evidence"]["stale_completed_priority_count"], 0)


if __name__ == "__main__":
    unittest.main()
