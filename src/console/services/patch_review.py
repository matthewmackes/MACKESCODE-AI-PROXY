"""Local patch review summaries for operator approval."""
import re
import subprocess
import time
from pathlib import Path


class PatchReviewService:
    """Summarize a git worktree without committing or exporting changes."""

    sensitive_re = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|dop_v1_[A-Za-z0-9_\-]+|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9._\-]+|token=[^&\s]+)", re.I)

    def __init__(self, default_project_dir, tmux_session_items=None, read_traces=None, create_session_snapshot=None, run_command=None, clock=None):
        self.default_project_dir = default_project_dir
        self.tmux_session_items = tmux_session_items or (lambda: [])
        self.read_traces = read_traces or (lambda **kwargs: [])
        self.create_session_snapshot = create_session_snapshot
        self.run_command = run_command or self.default_run
        self.clock = clock or time.time

    def default_run(self, args, cwd=None):
        return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=20)

    def payload(self, request=None):
        request = request if isinstance(request, dict) else {}
        project = self.project_dir(request)
        root = self.git_root(project)
        status_rows = self.status_rows(root)
        files = self.file_rows(root, status_rows)
        diff_excerpt = self.diff_excerpt(root)
        risks = self.risks(files, diff_excerpt)
        tests = self.tests(files)
        docs = self.docs_impact(files)
        session = str(request.get("session") or "").strip()
        traces = self.read_traces(limit=50, session=session) if session else []
        snapshot = None
        if session and request.get("include_snapshot") and self.create_session_snapshot:
            snapshot = self.create_session_snapshot({"session": session}).get("files")
        summary = self.summary(files, risks, tests, docs)
        return {
            "generated_at": self.clock(),
            "project_dir": str(project),
            "git_root": str(root),
            "session": session,
            "summary": summary,
            "files": files,
            "risks": risks,
            "tests": tests,
            "docs_impact": docs,
            "unresolved_concerns": self.concerns(files, tests),
            "suggested_commit_message": self.commit_message(files),
            "suggested_pr_description": self.pr_description(summary, files, risks, tests, docs),
            "diff_excerpt": diff_excerpt,
            "trace_links": [{"trace_id": row.get("trace_id"), "status": row.get("status"), "action": row.get("action")} for row in traces[:20]],
            "snapshot_files": snapshot,
            "operator_review_required": True,
            "privacy": "Diff excerpts are truncated and token-like strings are redacted. No commit or export is performed.",
        }

    def project_dir(self, request):
        if request.get("project_dir"):
            return Path(request.get("project_dir")).expanduser()
        session = str(request.get("session") or "").strip()
        if session:
            for item in self.tmux_session_items() or []:
                if item.get("name") == session and item.get("project_dir"):
                    return Path(item.get("project_dir")).expanduser()
        base = self.default_project_dir() if callable(self.default_project_dir) else self.default_project_dir
        return Path(base).expanduser()

    def git_root(self, project):
        result = self.run_command(["git", "rev-parse", "--show-toplevel"], cwd=str(project))
        if result.returncode != 0:
            raise ValueError("project is not inside a git repository")
        return Path(result.stdout.strip() or project)

    def git(self, root, *args):
        result = self.run_command(["git", *args], cwd=str(root))
        if result.returncode != 0:
            raise ValueError((result.stderr or "git command failed").strip())
        return result.stdout

    def status_rows(self, root):
        rows = []
        for line in self.git(root, "status", "--short").splitlines():
            if not line:
                continue
            rows.append({"status": line[:2].strip() or "modified", "path": line[3:]})
        return rows

    def file_rows(self, root, status_rows):
        numstat = {}
        for line in self.git(root, "diff", "--numstat").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                numstat[parts[2]] = {"additions": self.to_int(parts[0]), "deletions": self.to_int(parts[1])}
        rows = []
        for row in status_rows:
            path = row["path"]
            stat = numstat.get(path, {"additions": 0, "deletions": 0})
            rows.append({
                "path": path,
                "status": row["status"],
                "additions": stat["additions"],
                "deletions": stat["deletions"],
                "area": self.area(path),
                "kind": self.kind(path),
            })
        return rows

    def diff_excerpt(self, root):
        text = self.git(root, "diff", "--unified=0", "--no-ext-diff")
        return self.redact(text, 8000)

    def risks(self, files, diff):
        risks = []
        paths = " ".join(row.get("path") or "" for row in files)
        if any(row["area"] in {"auth", "security"} for row in files) or re.search(r"\b(token|secret|password|authorization)\b", diff, re.I):
            risks.append({"severity": "high", "area": "security", "detail": "Auth, secret, or authorization-sensitive code changed."})
        if "config/" in paths or "gateway-policy" in paths:
            risks.append({"severity": "medium", "area": "governance", "detail": "Runtime or governance configuration changed."})
        if any(row["kind"] == "test" for row in files):
            risks.append({"severity": "low", "area": "tests", "detail": "Test files changed; verify focused and release checks."})
        if not risks and files:
            risks.append({"severity": "low", "area": "general", "detail": "Review changed behavior and run focused tests."})
        return risks

    def tests(self, files):
        test_files = [row["path"] for row in files if row["kind"] == "test"]
        return {
            "changed_test_files": test_files,
            "suggested": ["python3 -m unittest discover -s tests -v"] if test_files else ["Run focused tests for changed modules", "./scripts/release-check.sh"],
            "missing_direct_tests": not bool(test_files),
        }

    def docs_impact(self, files):
        docs = [row["path"] for row in files if row["kind"] == "docs"]
        code = [row["path"] for row in files if row["kind"] == "code"]
        return {"docs_changed": docs, "code_changed": code, "docs_may_need_update": bool(code and not docs)}

    def concerns(self, files, tests):
        concerns = []
        if not files:
            concerns.append("No local changes were detected.")
        if tests.get("missing_direct_tests"):
            concerns.append("No test file changes were detected; verify runtime behavior with focused tests.")
        return concerns

    def summary(self, files, risks, tests, docs):
        return {
            "changed_files": len(files),
            "additions": sum(row.get("additions") or 0 for row in files),
            "deletions": sum(row.get("deletions") or 0 for row in files),
            "highest_risk": risks[0]["severity"] if risks else "none",
            "tests_changed": len(tests.get("changed_test_files") or []),
            "docs_changed": len(docs.get("docs_changed") or []),
        }

    def commit_message(self, files):
        areas = sorted({row["area"] for row in files if row.get("area")})
        subject = "Update %s" % (", ".join(areas[:2]) if areas else "project changes")
        return "%s\n\nSummarize behavior, tests, and rollout notes before committing." % subject

    def pr_description(self, summary, files, risks, tests, docs):
        return "\n".join([
            "## Summary",
            "- Changed %s files (+%s/-%s)" % (summary["changed_files"], summary["additions"], summary["deletions"]),
            "- Areas: %s" % (", ".join(sorted({row["area"] for row in files})) or "none"),
            "",
            "## Risks",
            *["- %s: %s" % (row["area"], row["detail"]) for row in risks],
            "",
            "## Tests",
            *["- %s" % item for item in tests.get("suggested") or []],
            "",
            "## Docs",
            "- Docs changed: %s" % (", ".join(docs.get("docs_changed") or []) or "none"),
        ])

    def area(self, path):
        if path.startswith("tests/"):
            return "tests"
        if path.startswith("docs/") or path.endswith(".md"):
            return "docs"
        if "auth" in path:
            return "auth"
        if "security" in path:
            return "security"
        if path.startswith("templates/") or path.startswith("frontend/"):
            return "ui"
        if path.startswith("config/") or "policy" in path:
            return "governance"
        return path.split("/", 1)[0] if "/" in path else "root"

    def kind(self, path):
        if path.startswith("tests/"):
            return "test"
        if path.startswith("docs/") or path.endswith(".md"):
            return "docs"
        if path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css")):
            return "code"
        return "asset"

    def redact(self, text, limit):
        clean = self.sensitive_re.sub("[redacted]", str(text or ""))
        return clean[:limit] + ("...[truncated]" if len(clean) > limit else "")

    def to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
