"""Workspace bundle import/export for local operator artifacts."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path


class WorkspaceBundleService:
    """Create and validate redacted workspace migration bundles."""

    schema_version = 1
    supported_sections = {
        "model_registry",
        "gateway_policy",
        "eval_datasets",
        "comparison_reports",
        "release_reports",
        "prompt_templates",
        "run_profiles",
    }
    sensitive_parts = ("token", "secret", "password", "authorization", "api_key", "access_key", "certificate", "private_key", "bearer")
    secret_pattern = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|dop_v1_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{12,}|token[=:][A-Za-z0-9._-]{12,})", re.I)

    def __init__(
        self,
        bundles_dir,
        model_registry_file,
        gateway_policy_file,
        evals_dir,
        comparison_reports_dir,
        release_reports_dir,
        run_store=None,
        append_audit=None,
        clock=None,
        uuid_factory=None,
        app_version="",
    ):
        self.bundles_dir = bundles_dir
        self.model_registry_file = model_registry_file
        self.gateway_policy_file = gateway_policy_file
        self.evals_dir = evals_dir
        self.comparison_reports_dir = comparison_reports_dir
        self.release_reports_dir = release_reports_dir
        self.run_store = run_store
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4
        self.app_version = app_version

    def directory(self):
        path = Path(self.bundles_dir())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, bundle_id):
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(bundle_id or ""))
        return self.directory() / ("%s.json" % (safe or "workspace-bundle"))

    def read_json(self, path, fallback):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, type(fallback)) else fallback
        except (OSError, ValueError, TypeError):
            return fallback

    def canonical(self, value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def checksum(self, value):
        return hashlib.sha256(self.canonical(value).encode("utf-8")).hexdigest()

    def redact(self, value):
        count = 0

        def walk(item):
            nonlocal count
            if isinstance(item, dict):
                clean = {}
                for key, child in item.items():
                    lowered = str(key).lower()
                    if any(part in lowered for part in self.sensitive_parts):
                        count += 1
                        clean[key] = "[redacted]"
                    else:
                        clean[key] = walk(child)
                return clean
            if isinstance(item, list):
                return [walk(child) for child in item]
            if isinstance(item, str):
                redacted = self.secret_pattern.sub("[redacted]", item)
                if redacted != item:
                    count += 1
                return redacted[:2000] + "...[truncated]" if len(redacted) > 2000 else redacted
            return item

        return walk(value), count

    def selected_sections(self, request):
        sections = request.get("sections") if isinstance(request.get("sections"), list) else []
        sections = [str(section) for section in sections if str(section) in self.supported_sections]
        return sections or sorted(self.supported_sections)

    def export_bundle(self, request=None, actor=None):
        request = request if isinstance(request, dict) else {}
        sections = self.selected_sections(request)
        raw = {section: self.export_section(section, request) for section in sections}
        redacted, redaction_count = self.redact(raw)
        checksums = {section: self.checksum(redacted.get(section)) for section in sections}
        bundle_id = str(request.get("id") or "workspace_bundle_%d_%s" % (int(self.clock()), self.uuid_factory().hex[:8]))
        manifest = {
            "schema_version": self.schema_version,
            "id": bundle_id,
            "created_at": float(self.clock()),
            "source_version": self.app_version,
            "sections": sections,
            "checksums": checksums,
            "redaction": {"mode": "strict", "redacted_values": redaction_count, "contains_sensitive": redaction_count > 0},
        }
        bundle = {"manifest": manifest, "sections": redacted}
        path = self.path_for(bundle_id)
        path.write_text(json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.append_audit("workspace_bundle.export", actor=actor or {}, outcome="completed", permission="workspace_bundle.export", request={"bundle_id": bundle_id, "sections": sections, "redacted_values": redaction_count}, status=200)
        return {"bundle": bundle, "bundle_id": bundle_id, "path": str(path), "summary": self.summary(bundle)}

    def export_section(self, section, request):
        if section == "model_registry":
            return {"models": self.read_json(self.model_registry_file(), [])}
        if section == "gateway_policy":
            return self.read_json(self.gateway_policy_file(), {})
        if section == "eval_datasets":
            return self.json_files(self.evals_dir(), selected=request.get("eval_dataset_ids"))
        if section == "comparison_reports":
            return self.json_files(self.comparison_reports_dir(), selected=request.get("comparison_report_ids"))
        if section == "release_reports":
            return self.json_files(self.release_reports_dir(), selected=request.get("release_report_ids"))
        if section == "prompt_templates":
            return self.safe_run_store_list("list_prompt_templates")
        if section == "run_profiles":
            return self.safe_run_store_list("list_run_profiles")
        return {}

    def json_files(self, directory, selected=None):
        root = Path(directory() if callable(directory) else directory)
        if not root.exists():
            return []
        selected = {str(item) for item in selected} if isinstance(selected, list) else set()
        rows = []
        for path in sorted(root.glob("*.json")):
            if selected and path.stem not in selected:
                continue
            data = self.read_json(path, {})
            if isinstance(data, dict):
                data = {**data, "_bundle_source_file": path.name}
            rows.append(data)
        return rows

    def safe_run_store_list(self, method):
        if not self.run_store:
            return []
        try:
            return getattr(self.run_store, method)()
        except Exception:
            return []

    def load_bundle(self, data):
        if isinstance(data, dict) and isinstance(data.get("manifest"), dict):
            return data
        if isinstance(data, dict) and data.get("path"):
            return self.read_json(Path(data.get("path")), {})
        if isinstance(data, dict) and data.get("bundle_id"):
            return self.read_json(self.path_for(data.get("bundle_id")), {})
        return {}

    def list_bundles(self):
        rows = []
        for path in sorted(self.directory().glob("*.json"), reverse=True):
            bundle = self.read_json(path, {})
            manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
            rows.append({
                "id": manifest.get("id") or path.stem,
                "path": str(path),
                "created_at": manifest.get("created_at") or 0,
                "sections": manifest.get("sections") or [],
                "redaction": manifest.get("redaction") or {},
                "valid": bool(manifest),
            })
        return {"bundles": rows}

    def preview_import(self, data):
        bundle = self.load_bundle(data)
        sections = None
        if isinstance(data, dict):
            sections = data.get("selected_sections") if isinstance(data.get("selected_sections"), list) else data.get("sections")
            sections = sections if isinstance(sections, list) else None
        return self.validate_bundle(bundle, sections=sections)

    def import_bundle(self, data, actor=None):
        data = data if isinstance(data, dict) else {}
        preview = self.preview_import(data)
        if preview["blocking"]:
            raise ValueError("bundle import has blocking validation issues")
        if data.get("dry_run", True):
            return preview
        bundle = self.load_bundle(data)
        sections = preview["selected_sections"]
        applied = []
        if "model_registry" in sections:
            models = ((bundle.get("sections") or {}).get("model_registry") or {}).get("models")
            if isinstance(models, list):
                self.model_registry_file().write_text(json.dumps(models, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                applied.append("model_registry")
        if "gateway_policy" in sections:
            policy = (bundle.get("sections") or {}).get("gateway_policy")
            if isinstance(policy, dict):
                self.gateway_policy_file().write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                applied.append("gateway_policy")
        if "eval_datasets" in sections:
            self.write_json_collection(self.evals_dir(), (bundle.get("sections") or {}).get("eval_datasets") or [], key="id")
            applied.append("eval_datasets")
        if "comparison_reports" in sections:
            self.write_json_collection(self.comparison_reports_dir(), (bundle.get("sections") or {}).get("comparison_reports") or [], key="id")
            applied.append("comparison_reports")
        if "release_reports" in sections:
            self.write_json_collection(self.release_reports_dir(), (bundle.get("sections") or {}).get("release_reports") or [], key="label", prefix="release-candidate")
            applied.append("release_reports")
        if "prompt_templates" in sections and self.run_store:
            for item in (bundle.get("sections") or {}).get("prompt_templates") or []:
                self.run_store.save_prompt_template(item)
            applied.append("prompt_templates")
        if "run_profiles" in sections and self.run_store:
            for item in (bundle.get("sections") or {}).get("run_profiles") or []:
                self.run_store.save_run_profile(item)
            applied.append("run_profiles")
        self.append_audit("workspace_bundle.import", actor=actor or {}, outcome="completed", permission="workspace_bundle.import", request={"bundle_id": preview["manifest"].get("id"), "sections": applied}, status=200)
        return {**preview, "applied": applied, "dry_run": False}

    def write_json_collection(self, directory, rows, key="id", prefix="item"):
        root = Path(directory() if callable(directory) else directory)
        root.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(rows if isinstance(rows, list) else [], start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("_bundle_source_file") or item.get(key) or "%s-%03d" % (prefix, index))
            safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in name)
            if not safe.endswith(".json"):
                safe += ".json"
            clean = dict(item)
            clean.pop("_bundle_source_file", None)
            (root / safe).write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def validate_bundle(self, bundle, sections=None):
        issues = []
        manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
        payload_sections = bundle.get("sections") if isinstance(bundle.get("sections"), dict) else {}
        selected = [section for section in (sections or manifest.get("sections") or payload_sections.keys()) if section in self.supported_sections]
        if int(manifest.get("schema_version") or 0) != self.schema_version:
            issues.append(self.issue("schema", "blocking", "Unsupported bundle schema_version", {"schema_version": manifest.get("schema_version")}))
        for section in selected:
            expected = (manifest.get("checksums") or {}).get(section)
            if expected and expected != self.checksum(payload_sections.get(section)):
                issues.append(self.issue("checksum", "blocking", "Section checksum mismatch", {"section": section}))
        secret_hits = self.secret_risks(payload_sections)
        if secret_hits:
            issues.append(self.issue("secret_risk", "blocking", "Bundle contains unredacted secret-bearing values", {"hits": secret_hits[:20]}))
        issues.extend(self.conflict_issues(payload_sections, selected))
        issues.extend(self.dependency_issues(payload_sections, selected))
        blocking = [issue for issue in issues if issue["severity"] == "blocking"]
        return {
            "manifest": manifest,
            "selected_sections": selected,
            "summary": self.summary(bundle),
            "issues": issues,
            "blocking": len(blocking) > 0,
            "dry_run": True,
        }

    def secret_risks(self, value, path=""):
        hits = []
        if isinstance(value, dict):
            for key, item in value.items():
                current = "%s.%s" % (path, key) if path else str(key)
                lowered = str(key).lower()
                if any(part in lowered for part in self.sensitive_parts) and item not in ("", None, "[redacted]"):
                    hits.append(current)
                hits.extend(self.secret_risks(item, current))
        elif isinstance(value, list):
            for index, item in enumerate(value[:200]):
                hits.extend(self.secret_risks(item, "%s[%d]" % (path, index)))
        elif isinstance(value, str) and self.secret_pattern.search(value):
            hits.append(path or "value")
        return hits

    def conflict_issues(self, sections, selected):
        issues = []
        if "eval_datasets" in selected:
            existing = {path.stem for path in Path(self.evals_dir()).glob("*.json")} if Path(self.evals_dir()).exists() else set()
            incoming = {str(item.get("id")) for item in sections.get("eval_datasets") or [] if isinstance(item, dict) and item.get("id")}
            for item_id in sorted(existing & incoming):
                issues.append(self.issue("conflict", "warning", "Eval dataset already exists", {"section": "eval_datasets", "id": item_id}))
        if "prompt_templates" in selected and self.run_store:
            existing = {item.get("id") for item in self.safe_run_store_list("list_prompt_templates")}
            incoming = {item.get("id") for item in sections.get("prompt_templates") or [] if isinstance(item, dict)}
            for item_id in sorted(existing & incoming):
                issues.append(self.issue("conflict", "warning", "Prompt template already exists", {"section": "prompt_templates", "id": item_id}))
        if "run_profiles" in selected and self.run_store:
            existing = {item.get("id") for item in self.safe_run_store_list("list_run_profiles")}
            incoming = {item.get("id") for item in sections.get("run_profiles") or [] if isinstance(item, dict)}
            for item_id in sorted(existing & incoming):
                issues.append(self.issue("conflict", "warning", "Run profile already exists", {"section": "run_profiles", "id": item_id}))
        return issues

    def dependency_issues(self, sections, selected):
        issues = []
        if "eval_datasets" in selected:
            for item in sections.get("eval_datasets") or []:
                if not isinstance(item, dict):
                    continue
                if int(item.get("schema_version") or self.schema_version) != self.schema_version:
                    issues.append(self.issue("schema", "blocking", "Unsupported eval dataset schema", {"id": item.get("id"), "schema_version": item.get("schema_version")}))
        if "run_profiles" in selected:
            bundled_templates = {item.get("id") for item in sections.get("prompt_templates") or [] if isinstance(item, dict)}
            existing_templates = {item.get("id") for item in self.safe_run_store_list("list_prompt_templates")} if self.run_store else set()
            for profile in sections.get("run_profiles") or []:
                template_id = profile.get("template_id") if isinstance(profile, dict) else ""
                if template_id and template_id not in bundled_templates and template_id not in existing_templates:
                    issues.append(self.issue("dependency", "blocking", "Run profile references missing prompt template", {"profile_id": profile.get("id"), "template_id": template_id}))
        return issues

    def summary(self, bundle):
        sections = bundle.get("sections") if isinstance(bundle.get("sections"), dict) else {}
        return {section: self.count_section(section, value) for section, value in sections.items()}

    def count_section(self, section, value):
        if section == "model_registry" and isinstance(value, dict):
            return len(value.get("models") or [])
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return 1 if value else 0
        return 0

    def issue(self, code, severity, message, details=None):
        return {"code": code, "severity": severity, "message": message, "details": details or {}}
