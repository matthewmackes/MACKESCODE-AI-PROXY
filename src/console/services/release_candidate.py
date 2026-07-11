"""Release candidate readiness aggregation."""
import json
import re
import time
from pathlib import Path


class ReleaseCandidateService:
    """Build local release-readiness reports from existing console evidence."""

    OPEN_WORKLIST_STATUSES = {"TODO", "IN_PROGRESS", "NEEDS_REVIEW", "BLOCKED"}

    def __init__(self, reports_dir, coverage_file, worklist_file, needs_operator_file, config_drift_payload, review_queue_payload, read_traces, list_eval_runs, clock=None):
        self.reports_dir = reports_dir
        self.coverage_file = coverage_file
        self.worklist_file = worklist_file
        self.needs_operator_file = needs_operator_file
        self.config_drift_payload = config_drift_payload
        self.review_queue_payload = review_queue_payload
        self.read_traces = read_traces
        self.list_eval_runs = list_eval_runs
        self.clock = clock or time.time

    def check(self, check_id, title, category, severity, passed, evidence=None, action=""):
        return {
            "id": check_id,
            "title": title,
            "category": category,
            "severity": severity,
            "status": "passed" if passed else "failed",
            "blocking": severity == "blocking",
            "evidence": evidence or {},
            "action": action,
        }

    def read_json_file(self, path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}

    def needs_operator_rows(self, text):
        rows = []
        for line in text.splitlines():
            if not line.startswith("| ") or line.startswith("| ---") or "Item | Needs | Status" in line:
                continue
            rows.append(line)
        return rows

    def parse_needs_operator_row(self, row):
        cells = [cell.strip() for cell in str(row or "").strip().strip("|").split("|")]
        item = cells[0] if len(cells) > 0 else ""
        needs = cells[1] if len(cells) > 1 else ""
        status = cells[2] if len(cells) > 2 else ""
        plan = self.operator_handoff_plan(item, needs, status)
        return {
            **plan,
            "item": cells[0] if len(cells) > 0 else "",
            "needs": cells[1] if len(cells) > 1 else "",
            "status": cells[2] if len(cells) > 2 else "",
            "closure_template": self.operator_handoff_closure_template(plan),
            "raw": row,
        }

    def operator_handoff_priority(self, gate_type):
        priorities = {
            "live-cloud": {
                "priority_order": 10,
                "urgency": "highest",
                "blocking_rationale": "Cloud capacity determines whether the selected LLM route can be offered publicly in the target region.",
            },
            "account-billing": {
                "priority_order": 20,
                "urgency": "high",
                "blocking_rationale": "Billing and prepay visibility determine whether live inference can keep serving after launch.",
            },
            "release-policy": {
                "priority_order": 30,
                "urgency": "high",
                "blocking_rationale": "Version, cadence, and tag policy must be chosen before a public release can be named and announced.",
            },
            "repository-admin": {
                "priority_order": 40,
                "urgency": "medium",
                "blocking_rationale": "Repository protections and security contacts must be configured once the publication target exists.",
            },
            "product-decision": {
                "priority_order": 50,
                "urgency": "medium",
                "blocking_rationale": "Unknown survey mappings must be restated or explicitly retired before product requirements are considered complete.",
            },
            "operator-decision": {
                "priority_order": 90,
                "urgency": "normal",
                "blocking_rationale": "This item needs an external operator decision before the advisory ledger can be closed.",
            },
        }
        return priorities.get(str(gate_type or "operator-decision"), priorities["operator-decision"])

    def ranked_operator_handoff_items(self, items):
        ranked = []
        for original_index, item in enumerate(items):
            priority = self.operator_handoff_priority(item.get("gate_type"))
            row = dict(item)
            row["priority_order"] = priority["priority_order"]
            row["urgency"] = priority["urgency"]
            row["blocking_rationale"] = priority["blocking_rationale"]
            row["original_index"] = original_index
            ranked.append(row)
        ranked.sort(key=lambda row: (int(row.get("priority_order") or 999), int(row.get("original_index") or 0)))
        for index, row in enumerate(ranked, start=1):
            row["priority_rank"] = index
        return ranked

    def operator_handoff_closure_template(self, plan):
        gate_type = str((plan or {}).get("gate_type") or "operator-decision")
        owner = str((plan or {}).get("owner") or "Operator")
        evidence = str((plan or {}).get("evidence_required") or "Operator decision, external state, timestamp, and updated status.")
        return "Status cell: Closed <YYYY-MM-DD>: <outcome>. Evidence: %s Owner: %s. Gate: %s." % (evidence, owner, gate_type)

    def operator_handoff_plan(self, item, needs, status):
        text = " ".join([str(item or ""), str(needs or ""), str(status or "")]).lower()
        if re.search(r"\b(billing|prepay|prepaid|balance|account)\b", text):
            return {
                "gate_type": "account-billing",
                "owner": "Account operator",
                "next_action": "Open the DigitalOcean billing/account view with a token that has billing visibility and capture the available billing/prepay signal.",
                "evidence_required": "Account identifier, billing visibility result, prepaid balance signal if available, timestamp, and any API limitation shown to the operator.",
            }
        if re.search(r"\b(digitalocean|gpu|capacity|region|model|live-cloud|live cloud)\b", text):
            return {
                "gate_type": "live-cloud",
                "owner": "Cloud operator",
                "next_action": "Check DigitalOcean model and GPU capacity in the target region, then record the exact available plan or fallback route.",
                "evidence_required": "Region, GPU/plan identifier, selected model, observed availability, timestamp, and fallback if capacity is unavailable.",
            }
        if re.search(r"\b(release|version|semantic|cadence|tag|changelog)\b", text):
            return {
                "gate_type": "release-policy",
                "owner": "Release owner",
                "next_action": "Choose the public version, release cadence, and tag process, then update release notes and changelog policy.",
                "evidence_required": "Chosen semantic version, tag naming rule, cadence decision, changelog entry, and release owner approval.",
            }
        if re.search(r"\b(github|repository|branch protection|required checks|security advisory)\b", text):
            return {
                "gate_type": "repository-admin",
                "owner": "Repository administrator",
                "next_action": "Configure repository settings, branch protection, required checks, and security contact preferences after publication.",
                "evidence_required": "Repository URL, branch protection summary, required check list, security advisory contact setting, and admin confirmation.",
            }
        if re.search(r"\b(survey|prompt|prompts|answer|requirements|product)\b", text):
            return {
                "gate_type": "product-decision",
                "owner": "Product owner",
                "next_action": "Restate the missing survey prompts or explicitly retire the unknown answer mappings from the product requirements.",
                "evidence_required": "Restated prompts with mapped answers, or a written decision that the compacted survey mappings are no longer required.",
            }
        return {
            "gate_type": "operator-decision",
            "owner": "Operator",
            "next_action": "Review the ledger row, perform the external/account decision, and update the status with the outcome.",
            "evidence_required": "Operator decision, external state or account result, timestamp, and the updated status location.",
        }

    def operator_handoff(self, checks=None):
        path = Path(self.needs_operator_file())
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                "source": str(path),
                "open_count": 0,
                "items": [],
                "blocking": True,
                "summary": "Operator-needed ledger is unavailable: %s" % exc,
            }
        rows = self.needs_operator_rows(text)
        items = self.ranked_operator_handoff_items([self.parse_needs_operator_row(row) for row in rows])
        blocking_failed = []
        advisory_failed = []
        for check in checks or []:
            if check.get("status") == "passed":
                continue
            if check.get("blocking"):
                blocking_failed.append(check.get("id"))
            else:
                advisory_failed.append(check.get("id"))
        if items:
            summary = "%d operator-owned release item%s remain before public release review." % (len(items), "" if len(items) == 1 else "s")
        else:
            summary = "No operator-owned release items are open."
        return {
            "source": str(path),
            "open_count": len(items),
            "items": items[:20],
            "blocking": False,
            "summary": summary,
            "blocking_failed_checks": blocking_failed,
            "advisory_failed_checks": advisory_failed,
        }

    def coverage_check(self):
        path = Path(self.coverage_file())
        report = self.read_json_file(path)
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        percent = float(summary.get("coverage_percent") or 0)
        passed = bool(summary) and percent >= 40.0
        return self.check(
            "coverage",
            "Coverage artifact and threshold",
            "release_check",
            "blocking",
            passed,
            {"path": str(path), "coverage_percent": percent, "summary": summary, "error": report.get("error", "")},
            "Run scripts/release-check.sh",
        )

    def release_artifacts_check(self):
        coverage = Path(self.coverage_file())
        return self.check(
            "release_check_artifacts",
            "Release-check artifacts",
            "release_check",
            "blocking",
            coverage.exists(),
            {"coverage": str(coverage), "browser_smoke": "covered by scripts/release-check.sh", "syntax": "covered by scripts/release-check.sh"},
            "Run scripts/release-check.sh",
        )

    def drift_check(self):
        payload = self.config_drift_payload()
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        drift_rows = payload.get("drift") if isinstance(payload.get("drift"), list) else []
        active_rows = [
            row for row in drift_rows
            if isinstance(row, dict) and row.get("changed", True) and not row.get("acknowledged")
        ]
        blocking_rows = [row for row in active_rows if str(row.get("risk") or "medium").lower() != "low"]
        advisory_rows = [row for row in active_rows if str(row.get("risk") or "medium").lower() == "low"]
        no_baseline = summary.get("state") == "no_baseline" or not summary.get("baseline_present", True)
        severity = "blocking" if no_baseline or blocking_rows else "advisory"
        passed = not no_baseline and not active_rows
        return self.check(
            "config_drift",
            "Config drift",
            "governance",
            severity,
            passed,
            {
                "summary": summary,
                "drift": drift_rows,
                "active_drift_count": len(active_rows),
                "blocking_drift_count": len(blocking_rows),
                "advisory_drift_count": len(advisory_rows),
                "blocking_drift": blocking_rows[:20],
                "advisory_drift": advisory_rows[:20],
            },
            "Open Console > System Operations > Config Drift",
        )

    def review_check(self):
        payload = self.review_queue_payload(status="open")
        rows = payload.get("reviews") if isinstance(payload.get("reviews"), list) else []
        high = [row for row in rows if row.get("severity") in {"critical", "high"}]
        severity = "blocking" if high else "advisory"
        return self.check(
            "open_reviews",
            "Open human review items",
            "governance",
            severity,
            not high,
            {"open": len(rows), "high_or_critical": len(high), "items": rows[:20]},
            "Resolve or close high-severity review items",
        )

    def needs_operator_check(self):
        path = Path(self.needs_operator_file())
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return self.check("needs_operator", "Operator-needed ledger", "governance", "blocking", False, {"path": str(path), "error": str(exc)})
        rows = self.needs_operator_rows(text)
        return self.check(
            "needs_operator",
            "Operator-needed items",
            "governance",
            "advisory",
            len(rows) == 0,
            {"path": str(path), "open_items": len(rows), "items": rows[:20]},
            "Review docs/NEEDS-OPERATOR.md before release",
        )

    def failed_trace_check(self):
        traces = self.read_traces(limit=200, status="error")
        cutoff = float(self.clock()) - 86400
        recent = [row for row in (traces or []) if float(row.get("timestamp") or 0) >= cutoff]
        return self.check(
            "recent_failed_traces",
            "Recent failed traces",
            "observability",
            "blocking",
            len(recent) == 0,
            {"recent_failed": len(recent), "traces": recent[:20]},
            "Inspect Console > Observability",
        )

    def eval_check(self):
        runs = self.list_eval_runs(limit=10)
        failures = []
        for run in runs or []:
            for summary in run.get("summary") or []:
                if int(summary.get("failures") or 0) > 0:
                    failures.append({"run_id": run.get("id"), "dataset": run.get("dataset"), "model": summary.get("model"), "failures": summary.get("failures")})
        return self.check(
            "eval_failures",
            "Recent eval failures",
            "quality",
            "blocking",
            len(failures) == 0,
            {"failures": failures[:20], "runs_checked": len(runs or [])},
            "Open AgentBoard > Evals",
        )

    def governance_docs_check(self):
        required = ["GOVERNANCE.md", "RELEASE.md", "SECURITY.md", "CHANGELOG.md"]
        missing = [name for name in required if not (Path(self.worklist_file()).parent / name).exists()]
        return self.check(
            "governance_docs",
            "Release governance docs",
            "governance",
            "blocking",
            not missing,
            {"required": required, "missing": missing},
        )

    def requirements_ledger_file(self):
        return Path(self.worklist_file()).parent / "docs" / "requirements-ledger.md"

    def section_text(self, text, heading):
        match = re.search(r"^## %s\s*$" % re.escape(heading), text, flags=re.M)
        if not match:
            return ""
        next_heading = re.search(r"^##\s+", text[match.end():], flags=re.M)
        end = match.end() + next_heading.start() if next_heading else len(text)
        return text[match.end():end]

    def numbered_priority_rows(self, text):
        section = self.section_text(text, "Priority Order")
        rows = []
        for line_no, line in enumerate(section.splitlines(), start=1):
            match = re.match(r"\s*(\d+)\.\s+(.+)$", line)
            if not match:
                continue
            task_ids = re.findall(r"\b(?:INT|V2)-\d+\b", match.group(2))
            rows.append({"rank": int(match.group(1)), "text": match.group(2).strip(), "task_ids": task_ids, "section_line": line_no})
        return rows

    def requirements_ledger_check(self):
        ledger_path = self.requirements_ledger_file()
        try:
            ledger_text = ledger_path.read_text(encoding="utf-8")
        except OSError as exc:
            return self.check(
                "requirements_ledger",
                "Requirements ledger freshness",
                "governance",
                "advisory",
                False,
                {"path": str(ledger_path), "error": str(exc)},
                "Update docs/requirements-ledger.md",
            )
        try:
            worklist_text = Path(self.worklist_file()).read_text(encoding="utf-8")
        except OSError as exc:
            return self.check(
                "requirements_ledger",
                "Requirements ledger freshness",
                "governance",
                "advisory",
                False,
                {"path": str(ledger_path), "worklist_error": str(exc)},
                "Update docs/requirements-ledger.md after worklist recovery",
            )
        tasks = {task.get("id"): task for task in self.worklist_tasks(worklist_text) if task.get("id")}
        priority_rows = self.numbered_priority_rows(ledger_text)
        stale_rows = []
        for row in priority_rows:
            completed = [
                tasks[task_id]
                for task_id in row.get("task_ids") or []
                if task_id in tasks and tasks[task_id].get("status") in {"COMPLETED", "CANCELLED"}
            ]
            if completed:
                stale_rows.append({**row, "completed_tasks": completed})
        return self.check(
            "requirements_ledger",
            "Requirements ledger freshness",
            "governance",
            "advisory",
            len(stale_rows) == 0,
            {
                "path": str(ledger_path),
                "priority_item_count": len(priority_rows),
                "stale_completed_priority_count": len(stale_rows),
                "stale_completed_priorities": stale_rows[:20],
            },
            "Update docs/requirements-ledger.md Priority Order",
        )

    def worklist_task_source(self, text):
        def keep_line_count(match):
            return "\n" * match.group(0).count("\n")

        return re.sub(r"^```.*?^```[^\n]*(?:\n|$)", keep_line_count, text, flags=re.M | re.S)

    def worklist_tasks(self, text):
        text = self.worklist_task_source(text)
        tasks = []
        for match in re.finditer(r"^### Task ID:.*?(?=^### Task ID:|\Z)", text, flags=re.M | re.S):
            block = match.group(0)
            line = text.count("\n", 0, match.start()) + 1
            task_id = ""
            title = ""
            status = ""
            priority = ""
            task_match = re.search(r"^### Task ID:\s*(.+?)\s*$", block, flags=re.M)
            title_match = re.search(r"^\*\*Title:\*\*\s*(.+?)\s*$", block, flags=re.M)
            status_match = re.search(r"^\*\*Status:\*\*\s*(.+?)\s*$", block, flags=re.M)
            priority_match = re.search(r"^\*\*Priority:\*\*\s*(P[0-3])\b", block, flags=re.M)
            if task_match:
                task_id = task_match.group(1).strip()
            if title_match:
                title = title_match.group(1).strip()
            if priority_match:
                priority = priority_match.group(1).strip()
            if status_match:
                status_line = status_match.group(1)
                status_token = re.search(r"`([A-Z_]+)`", status_line)
                status = (status_token.group(1) if status_token else status_line).strip()
            tasks.append({"id": task_id, "title": title, "status": status, "priority": priority, "line": line})
        return tasks

    def pending_priority_worklist_items(self, text):
        return [
            task
            for task in self.worklist_tasks(text)
            if task.get("priority") in {"P0", "P1"} and task.get("status") in self.OPEN_WORKLIST_STATUSES
        ]

    def duplicate_worklist_task_ids(self, tasks):
        occurrences = {}
        for task in tasks:
            task_id = task.get("id")
            if not task_id:
                continue
            occurrences.setdefault(task_id, []).append(task)
        return [
            {
                "id": task_id,
                "count": len(rows),
                "tasks": rows[:10],
            }
            for task_id, rows in sorted(occurrences.items())
            if len(rows) > 1
        ]

    def worklist_check(self):
        path = Path(self.worklist_file())
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return self.check("worklist", "Worklist status", "governance", "blocking", False, {"path": str(path), "error": str(exc)})
        tasks = self.worklist_tasks(text)
        pending_items = self.pending_priority_worklist_items(text)
        duplicate_task_ids = self.duplicate_worklist_task_ids(tasks)
        return self.check(
            "worklist",
            "P1 worklist and task identity status",
            "governance",
            "advisory",
            len(pending_items) == 0 and len(duplicate_task_ids) == 0,
            {
                "path": str(path),
                "pending_p1_estimate": len(pending_items),
                "pending_items": pending_items[:20],
                "duplicate_task_count": len(duplicate_task_ids),
                "duplicate_task_ids": duplicate_task_ids[:20],
            },
            "Review MAIN-WORKLIST.md for unreleased scope",
        )

    def checks(self):
        return [
            self.release_artifacts_check(),
            self.coverage_check(),
            self.drift_check(),
            self.review_check(),
            self.needs_operator_check(),
            self.failed_trace_check(),
            self.eval_check(),
            self.governance_docs_check(),
            self.requirements_ledger_check(),
            self.worklist_check(),
        ]

    def payload(self):
        checks = self.checks()
        blocking_failed = [row for row in checks if row.get("blocking") and row.get("status") != "passed"]
        advisory_failed = [row for row in checks if not row.get("blocking") and row.get("status") != "passed"]
        handoff = self.operator_handoff(checks)
        return {
            "generated_at": float(self.clock()),
            "ready": len(blocking_failed) == 0,
            "summary": {
                "checks": len(checks),
                "blocking_failed": len(blocking_failed),
                "advisory_failed": len(advisory_failed),
                "passed": len([row for row in checks if row.get("status") == "passed"]),
            },
            "checks": checks,
            "operator_handoff": handoff,
            "actions": {
                "release_check": "scripts/release-check.sh",
                "health_validate": "python3 scripts/health-validate.py",
                "release_notes": "Review CHANGELOG.md and RELEASE.md",
            },
        }

    def write_report(self, request=None):
        request = request if isinstance(request, dict) else {}
        report = self.payload()
        report["label"] = str(request.get("label") or "release-candidate")
        root = Path(self.reports_dir())
        root.mkdir(parents=True, exist_ok=True)
        path = root / ("release-candidate-%d.json" % int(self.clock()))
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["report_file"] = str(path)
        return report
