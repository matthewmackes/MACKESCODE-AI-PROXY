"""Repository issue and pull request context import helpers."""
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class GitHubContextConnector:
    """Minimal GitHub REST connector for issue and pull request metadata."""

    api_root = "https://api.github.com"

    def __init__(self, token_provider=None, urlopen_func=None, clock=None):
        self.token_provider = token_provider or (lambda: os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
        self.urlopen = urlopen_func or urlopen
        self.clock = clock or time.time

    def configured(self):
        return bool(str(self.token_provider() or "").strip())

    def headers(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mde-llm-proxy-console",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = str(self.token_provider() or "").strip()
        if token:
            headers["Authorization"] = "Bearer %s" % token
        return headers

    def get(self, path):
        if not self.configured():
            raise RuntimeError("GitHub token is not configured")
        request = Request("%s%s" % (self.api_root, path), headers=self.headers())
        try:
            with self.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError("GitHub request failed: HTTP %s %s" % (exc.code, detail))
        except URLError as exc:
            raise RuntimeError("GitHub request failed: %s" % exc.reason)
        return json.loads(body or "{}")

    def fetch(self, ref):
        owner, repo, number = ref["owner"], ref["repo"], ref["number"]
        issue = self.get("/repos/%s/%s/issues/%s" % (owner, repo, number))
        comments = self.list_items("/repos/%s/%s/issues/%s/comments?per_page=20" % (owner, repo, number))
        is_pr = isinstance(issue.get("pull_request"), dict)
        payload = {"issue": issue, "comments": comments, "is_pr": is_pr}
        if is_pr:
            pull = self.get("/repos/%s/%s/pulls/%s" % (owner, repo, number))
            files = self.list_items("/repos/%s/%s/pulls/%s/files?per_page=50" % (owner, repo, number))
            reviews = self.list_items("/repos/%s/%s/pulls/%s/reviews?per_page=20" % (owner, repo, number))
            review_comments = self.list_items("/repos/%s/%s/pulls/%s/comments?per_page=20" % (owner, repo, number))
            sha = ((pull.get("head") or {}).get("sha") or "").strip()
            checks = {}
            if sha:
                try:
                    checks = self.get("/repos/%s/%s/commits/%s/check-runs?per_page=20" % (owner, repo, sha))
                except RuntimeError as exc:
                    checks = {"error": str(exc)}
            payload.update({"pull": pull, "files": files, "reviews": reviews, "review_comments": review_comments, "checks": checks})
        return payload

    def list_items(self, path):
        data = self.get(path)
        return data if isinstance(data, list) else []


class RepositoryContextService:
    """Build redacted issue/PR context previews for Claude Code sessions."""

    token_re = re.compile(r"(gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9._\-]+|token=[^&\s]+)", re.I)

    def __init__(self, connector=None, project_dir=None, worklist_text=None, clock=None):
        self.connector = connector or GitHubContextConnector()
        self.project_dir = project_dir or (lambda: "")
        self.worklist_text = worklist_text or (lambda: "")
        self.clock = clock or time.time

    def payload(self):
        return {
            "connectors": [{
                "id": "github",
                "label": "GitHub",
                "configured": bool(self.connector.configured()),
                "capabilities": ["issues", "pull_requests", "comments", "files", "checks", "reviews"],
            }],
            "privacy": "Repository context previews are redacted and bounded before they are added to Claude Code prompts.",
        }

    def parse_reference(self, value):
        text = str(value or "").strip()
        if not text:
            raise ValueError("repository issue or PR reference is required")
        parsed = urlparse(text)
        if parsed.netloc.lower() == "github.com":
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 4 and parts[2] in {"issues", "pull"}:
                return {"provider": "github", "owner": parts[0], "repo": parts[1], "kind_hint": "pr" if parts[2] == "pull" else "issue", "number": int(parts[3]), "url": text}
        match = re.match(r"^([\w.-]+)/([\w.-]+)#(\d+)$", text)
        if match:
            return {"provider": "github", "owner": match.group(1), "repo": match.group(2), "kind_hint": "unknown", "number": int(match.group(3)), "url": "https://github.com/%s/%s/issues/%s" % (match.group(1), match.group(2), match.group(3))}
        raise ValueError("reference must be a GitHub issue/PR URL or owner/repo#number")

    def preview(self, request):
        request = request if isinstance(request, dict) else {}
        ref = self.parse_reference(request.get("reference") or request.get("url") or request.get("target"))
        raw = {}
        warnings = []
        degraded = False
        if self.connector.configured():
            try:
                raw = self.connector.fetch(ref)
            except Exception as exc:
                degraded = True
                warnings.append({"severity": "warning", "code": "github_fetch_failed", "message": str(exc)})
        else:
            degraded = True
            warnings.append({"severity": "warning", "code": "github_token_missing", "message": "GITHUB_TOKEN or GH_TOKEN is not configured; preview is limited to the parsed reference."})
        context = self.context_from_raw(ref, raw, warnings)
        context["degraded"] = degraded
        prompt = self.prompt_text(context)
        return {
            "generated_at": self.clock(),
            "provider": "github",
            "configured": bool(self.connector.configured()),
            "degraded": degraded,
            "reference": ref,
            "context": context,
            "prompt": prompt,
            "prompt_chars": len(prompt),
            "warnings": warnings,
            "imported_context": self.import_metadata(context),
        }

    def import_payload(self, request):
        preview = self.preview(request)
        return {
            "preview": preview,
            "launch_patch": {
                "print_prompt_append": preview["prompt"],
                "imported_context": preview["imported_context"],
            },
        }

    def context_from_raw(self, ref, raw, warnings):
        issue = raw.get("issue") if isinstance(raw.get("issue"), dict) else {}
        pull = raw.get("pull") if isinstance(raw.get("pull"), dict) else {}
        is_pr = bool(raw.get("is_pr") or pull)
        title = issue.get("title") or pull.get("title") or "%s/%s#%s" % (ref["owner"], ref["repo"], ref["number"])
        body = issue.get("body") or pull.get("body") or ""
        labels = [item.get("name") for item in issue.get("labels") or [] if isinstance(item, dict) and item.get("name")]
        assignees = [item.get("login") for item in issue.get("assignees") or [] if isinstance(item, dict) and item.get("login")]
        files = self.file_rows(raw.get("files") or [])
        checks = self.check_rows(raw.get("checks") if isinstance(raw.get("checks"), dict) else {})
        reviews = self.review_rows(raw.get("reviews") or [], raw.get("review_comments") or [])
        comments = self.comment_rows(raw.get("comments") or [])
        links = self.worklist_links(ref, title)
        return {
            "provider": "github",
            "kind": "pull_request" if is_pr else "issue",
            "owner": ref["owner"],
            "repo": ref["repo"],
            "number": ref["number"],
            "url": issue.get("html_url") or pull.get("html_url") or ref.get("url"),
            "title": self.redact_text(title, 240),
            "state": issue.get("state") or pull.get("state") or "unknown",
            "author": ((issue.get("user") or pull.get("user") or {}).get("login") if isinstance(issue.get("user") or pull.get("user"), dict) else "") or "",
            "labels": labels[:20],
            "assignees": assignees[:20],
            "body_preview": self.redact_text(body, 1800),
            "base": (pull.get("base") or {}).get("ref") if isinstance(pull.get("base"), dict) else "",
            "head": (pull.get("head") or {}).get("ref") if isinstance(pull.get("head"), dict) else "",
            "head_sha": (pull.get("head") or {}).get("sha") if isinstance(pull.get("head"), dict) else "",
            "changed_files": files,
            "checks": checks,
            "comments": comments,
            "reviews": reviews,
            "linked_worklist": links,
            "warnings": warnings,
            "privacy": "Comments, bodies, and diagnostics are truncated and token-like strings are redacted.",
        }

    def file_rows(self, files):
        rows = []
        for item in files[:50]:
            if not isinstance(item, dict):
                continue
            rows.append({
                "filename": item.get("filename") or "",
                "status": item.get("status") or "",
                "additions": int(item.get("additions") or 0),
                "deletions": int(item.get("deletions") or 0),
                "changes": int(item.get("changes") or 0),
                "patch_preview": self.redact_text(item.get("patch") or "", 600),
            })
        return rows

    def check_rows(self, checks):
        rows = []
        for item in checks.get("check_runs") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "name": item.get("name") or "",
                "status": item.get("status") or "",
                "conclusion": item.get("conclusion") or "",
                "details_url": item.get("details_url") or "",
                "output_summary": self.redact_text((item.get("output") or {}).get("summary") if isinstance(item.get("output"), dict) else "", 800),
                "output_text": self.redact_text((item.get("output") or {}).get("text") if isinstance(item.get("output"), dict) else "", 1200),
            })
        return rows[:20]

    def comment_rows(self, comments):
        rows = []
        for item in comments[:20]:
            if not isinstance(item, dict):
                continue
            rows.append({"author": ((item.get("user") or {}).get("login") if isinstance(item.get("user"), dict) else "") or "", "body": self.redact_text(item.get("body") or "", 700), "url": item.get("html_url") or ""})
        return rows

    def review_rows(self, reviews, review_comments):
        rows = []
        for item in reviews[:20]:
            if isinstance(item, dict):
                rows.append({"author": ((item.get("user") or {}).get("login") if isinstance(item.get("user"), dict) else "") or "", "state": item.get("state") or "", "body": self.redact_text(item.get("body") or "", 500), "url": item.get("html_url") or ""})
        for item in review_comments[:20]:
            if isinstance(item, dict):
                rows.append({"author": ((item.get("user") or {}).get("login") if isinstance(item.get("user"), dict) else "") or "", "state": "comment", "path": item.get("path") or "", "body": self.redact_text(item.get("body") or "", 500), "url": item.get("html_url") or ""})
        return rows[:30]

    def worklist_links(self, ref, title):
        text = self.worklist_text() or ""
        needles = [
            "%s/%s#%s" % (ref["owner"], ref["repo"], ref["number"]),
            "github.com/%s/%s/issues/%s" % (ref["owner"], ref["repo"], ref["number"]),
            "github.com/%s/%s/pull/%s" % (ref["owner"], ref["repo"], ref["number"]),
            "#%s" % ref["number"],
            str(title or "")[:80],
        ]
        rows = []
        for line in text.splitlines():
            if any(needle and needle in line for needle in needles):
                rows.append(self.redact_text(line.strip(), 300))
            if len(rows) >= 10:
                break
        return rows

    def prompt_text(self, context):
        files = context.get("changed_files") or []
        checks = context.get("checks") or []
        comments = context.get("comments") or []
        reviews = context.get("reviews") or []
        lines = [
            "Repository context import",
            "Source: GitHub %s %s/%s#%s" % (context.get("kind"), context.get("owner"), context.get("repo"), context.get("number")),
            "Title: %s" % context.get("title"),
            "State: %s" % context.get("state"),
            "URL: %s" % context.get("url"),
            "Labels: %s" % (", ".join(context.get("labels") or []) or "none"),
            "Assignees: %s" % (", ".join(context.get("assignees") or []) or "none"),
        ]
        if context.get("base") or context.get("head"):
            lines.append("Branch: %s <- %s" % (context.get("base") or "base", context.get("head") or "head"))
        if context.get("body_preview"):
            lines += ["", "Body:", context.get("body_preview")]
        if files:
            lines += ["", "Changed files:"]
            lines.extend("- {filename} ({status}, +{additions}/-{deletions}, {changes} changes)".format(**row) for row in files[:25])
        if checks:
            lines += ["", "CI/check status:"]
            lines.extend("- %s: %s %s" % (row.get("name"), row.get("status"), row.get("conclusion")) for row in checks[:15])
        if reviews:
            lines += ["", "Review context:"]
            lines.extend("- %s %s%s: %s" % (row.get("author"), row.get("state"), (" on " + row.get("path")) if row.get("path") else "", row.get("body")) for row in reviews[:12])
        if comments:
            lines += ["", "Recent comments:"]
            lines.extend("- %s: %s" % (row.get("author"), row.get("body")) for row in comments[:12])
        if context.get("linked_worklist"):
            lines += ["", "Linked worklist items:"]
            lines.extend("- %s" % item for item in context.get("linked_worklist")[:10])
        if context.get("warnings"):
            lines += ["", "Import warnings:"]
            lines.extend("- %s: %s" % (row.get("code"), row.get("message")) for row in context.get("warnings")[:5])
        lines += ["", "Use this repository context as background. Do not assume credentials are available in the session."]
        return self.redact_text("\n".join(lines), 12000)

    def import_metadata(self, context):
        return {
            "provider": "github",
            "kind": context.get("kind"),
            "owner": context.get("owner"),
            "repo": context.get("repo"),
            "number": context.get("number"),
            "url": context.get("url"),
            "title": context.get("title"),
            "head_sha": context.get("head_sha") or "",
            "changed_files": [{"filename": row.get("filename"), "status": row.get("status"), "changes": row.get("changes")} for row in (context.get("changed_files") or [])[:50]],
            "checks": [{"name": row.get("name"), "status": row.get("status"), "conclusion": row.get("conclusion")} for row in (context.get("checks") or [])[:20]],
            "linked_worklist": context.get("linked_worklist") or [],
            "imported_at": self.clock(),
        }

    def redact_text(self, value, limit=None):
        text = self.token_re.sub("[redacted]", str(value or ""))
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return text[:limit] + ("...[truncated]" if limit and len(text) > limit else "") if limit else text
