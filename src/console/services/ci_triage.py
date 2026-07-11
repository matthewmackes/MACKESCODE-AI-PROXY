"""CI failure triage built from repository context imports."""


class CiTriageService:
    """Summarize failed CI checks and shape a Claude Code fix-session prompt."""

    SUCCESS_CONCLUSIONS = {"success", "skipped", "neutral"}

    def __init__(self, repository_context, failure_taxonomy=None, clock=None):
        self.repository_context = repository_context
        self.failure_taxonomy = failure_taxonomy
        self.clock = clock

    def payload(self):
        base = self.repository_context.payload()
        return {
            "connectors": base.get("connectors") or [],
            "privacy": "CI triage uses redacted repository context and stores compact metadata only.",
            "supported": ["github_checks", "pull_request_files", "review_comments"],
        }

    def preview(self, request):
        repo = self.repository_context.preview(request)
        context = repo.get("context") or {}
        failures = self.failures(context)
        prompt = self.prompt(context, failures, repo.get("warnings") or [])
        imported = dict(repo.get("imported_context") or {})
        imported["ci_failures"] = [{"name": row.get("name"), "conclusion": row.get("conclusion"), "category": (row.get("failure") or {}).get("category")} for row in failures]
        return {
            "generated_at": repo.get("generated_at"),
            "degraded": repo.get("degraded"),
            "reference": repo.get("reference"),
            "context": {
                "provider": context.get("provider"),
                "kind": context.get("kind"),
                "owner": context.get("owner"),
                "repo": context.get("repo"),
                "number": context.get("number"),
                "title": context.get("title"),
                "url": context.get("url"),
                "changed_files": context.get("changed_files") or [],
            },
            "failures": failures,
            "failure_count": len(failures),
            "prompt": prompt,
            "warnings": repo.get("warnings") or [],
            "launch_patch": {"print_prompt_append": prompt, "imported_context": imported},
        }

    def failures(self, context):
        files = context.get("changed_files") or []
        affected = [{"filename": row.get("filename"), "status": row.get("status"), "changes": row.get("changes")} for row in files[:12]]
        rows = []
        for check in context.get("checks") or []:
            conclusion = str(check.get("conclusion") or "").lower()
            status = str(check.get("status") or "").lower()
            if status == "completed" and conclusion in self.SUCCESS_CONCLUSIONS:
                continue
            if not conclusion and status in {"queued", "in_progress"}:
                continue
            text = " ".join(str(check.get(key) or "") for key in ("name", "status", "conclusion", "output_summary", "output_text"))
            failure = self.classify(text)
            rows.append({
                "name": check.get("name") or "check",
                "status": check.get("status") or "",
                "conclusion": check.get("conclusion") or "",
                "details_url": check.get("details_url") or "",
                "failure": failure,
                "log_excerpt": self.excerpt(check),
                "affected_files": affected,
            })
        return rows

    def classify(self, text):
        if self.failure_taxonomy is not None:
            return self.failure_taxonomy.classify({"message": text})
        return {"category": "unknown", "title": "Unclassified failure", "suggested_fix": "Inspect CI logs and changed files."}

    def excerpt(self, check):
        text = "\n".join(str(check.get(key) or "") for key in ("output_summary", "output_text") if check.get(key))
        text = text.strip()
        return text[:1200] + ("...[truncated]" if len(text) > 1200 else "")

    def prompt(self, context, failures, warnings):
        lines = [
            "CI failure triage",
            "Source: %s/%s#%s" % (context.get("owner"), context.get("repo"), context.get("number")),
            "Title: %s" % (context.get("title") or "n/a"),
            "URL: %s" % (context.get("url") or "n/a"),
            "",
            "Failed checks:",
        ]
        if failures:
            for row in failures:
                failure = row.get("failure") or {}
                lines.append("- %s: %s %s [%s]" % (row.get("name"), row.get("status"), row.get("conclusion"), failure.get("category") or "unknown"))
                if row.get("log_excerpt"):
                    lines.append("  excerpt: %s" % row.get("log_excerpt").replace("\n", " ")[:500])
        else:
            lines.append("- No failed checks were found in the imported context.")
        files = context.get("changed_files") or []
        if files:
            lines += ["", "Likely affected files:"]
            lines.extend("- %s (%s, %s changes)" % (row.get("filename"), row.get("status"), row.get("changes")) for row in files[:20])
        if warnings:
            lines += ["", "Import warnings:"]
            lines.extend("- %s: %s" % (row.get("code"), row.get("message")) for row in warnings[:5])
        lines += ["", "Task: inspect the failed checks, repair the likely affected files, and run focused tests before summarizing the fix."]
        return "\n".join(lines)
