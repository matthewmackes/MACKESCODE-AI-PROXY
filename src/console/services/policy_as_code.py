"""Validated policy bundle import/export and apply workflow."""
import hashlib
import json
import time
from pathlib import Path


class PolicyAsCodeService:
    """Unify local policy sections behind a validated bundle contract."""

    SCHEMA_VERSION = 1
    SECTIONS = {"gateway", "budgets", "quotas", "automation", "rbac", "eval_gates"}
    SENSITIVE_PARTS = ("token", "secret", "password", "authorization", "api_key", "access_key")

    def __init__(
        self,
        policy_file,
        history_file,
        gateway_policy_file,
        budget_file,
        automation_rules_file,
        role_permissions,
        quota_config,
        eval_gate_policy=None,
        append_audit=None,
        clock=None,
    ):
        self.policy_file = policy_file
        self.history_file = history_file
        self.gateway_policy_file = gateway_policy_file
        self.budget_file = budget_file
        self.automation_rules_file = automation_rules_file
        self.role_permissions = role_permissions
        self.quota_config = quota_config
        self.eval_gate_policy = eval_gate_policy or (lambda: {"schema_version": 1, "default_policy": {"require_pass": False}})
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time

    def load_json(self, path_func, default):
        path = Path(path_func())
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def write_json(self, path_func, data):
        path = Path(path_func())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def fingerprint(self, data):
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def current_bundle(self):
        return {
            "schema_version": self.SCHEMA_VERSION,
            "policies": {
                "gateway": self.load_json(self.gateway_policy_file, {"schema_version": 1}),
                "budgets": self.load_json(self.budget_file, {}),
                "quotas": self.quota_config() or {},
                "automation": self.load_json(self.automation_rules_file, {"schema_version": 1, "rules": []}),
                "rbac": {"schema_version": 1, "roles": {key: sorted(list(value)) for key, value in (self.role_permissions() or {}).items()}},
                "eval_gates": self.eval_gate_policy() or {"schema_version": 1, "default_policy": {}},
            },
        }

    def load_bundle(self):
        return self.load_json(self.policy_file, self.current_bundle())

    def save_bundle(self, bundle):
        return self.write_json(self.policy_file, bundle)

    def secret_paths(self, value, prefix=""):
        paths = []
        if isinstance(value, dict):
            for key, item in value.items():
                path = ("%s.%s" % (prefix, key)).strip(".")
                if any(part in str(key).lower() for part in self.SENSITIVE_PARTS):
                    paths.append(path)
                paths.extend(self.secret_paths(item, path))
        elif isinstance(value, list):
            for index, item in enumerate(value[:200]):
                paths.extend(self.secret_paths(item, "%s[%s]" % (prefix, index)))
        return paths

    def issue(self, section, severity, message, path=""):
        return {"section": section, "severity": severity, "message": message, "path": path}

    def validate(self, bundle):
        issues = []
        if not isinstance(bundle, dict):
            return [self.issue("bundle", "error", "policy bundle must be a JSON object")]
        try:
            schema_version = int(bundle.get("schema_version") or 0)
        except (TypeError, ValueError):
            schema_version = 0
        if schema_version != self.SCHEMA_VERSION:
            issues.append(self.issue("bundle", "error", "schema_version must be 1", "schema_version"))
        policies = bundle.get("policies")
        if not isinstance(policies, dict):
            return issues + [self.issue("bundle", "error", "policies must be an object", "policies")]
        unknown = sorted(set(policies) - self.SECTIONS)
        for section in unknown:
            issues.append(self.issue(section, "warning", "unknown policy section will be stored but not applied", "policies.%s" % section))
        for section, policy in policies.items():
            for path in self.secret_paths(policy, "policies.%s" % section):
                issues.append(self.issue(section, "error", "secret-like keys are not allowed in policy files", path))
        gateway = policies.get("gateway")
        if gateway is not None and not isinstance(gateway, dict):
            issues.append(self.issue("gateway", "error", "gateway policy must be an object", "policies.gateway"))
        budgets = policies.get("budgets")
        if budgets is not None:
            if not isinstance(budgets, dict):
                issues.append(self.issue("budgets", "error", "budgets policy must be an object", "policies.budgets"))
            else:
                for key in ("daily_usd", "monthly_usd", "total_usd"):
                    if key in budgets:
                        try:
                            if float(budgets.get(key) or 0) < 0:
                                issues.append(self.issue("budgets", "error", "%s cannot be negative" % key, "policies.budgets.%s" % key))
                        except (TypeError, ValueError):
                            issues.append(self.issue("budgets", "error", "%s must be numeric" % key, "policies.budgets.%s" % key))
        quotas = policies.get("quotas")
        if quotas is not None and not isinstance(quotas, dict):
            issues.append(self.issue("quotas", "error", "quotas policy must be an object", "policies.quotas"))
        automation = policies.get("automation")
        if automation is not None:
            if not isinstance(automation, dict):
                issues.append(self.issue("automation", "error", "automation policy must be an object", "policies.automation"))
            elif not isinstance(automation.get("rules", []), list):
                issues.append(self.issue("automation", "error", "automation rules must be a list", "policies.automation.rules"))
        rbac = policies.get("rbac")
        if rbac is not None:
            roles = rbac.get("roles") if isinstance(rbac, dict) else None
            if not isinstance(roles, dict):
                issues.append(self.issue("rbac", "error", "rbac.roles must be an object", "policies.rbac.roles"))
            else:
                for role, permissions in roles.items():
                    if not isinstance(permissions, list):
                        issues.append(self.issue("rbac", "error", "role permissions must be lists", "policies.rbac.roles.%s" % role))
        eval_gates = policies.get("eval_gates")
        if eval_gates is not None and not isinstance(eval_gates, dict):
            issues.append(self.issue("eval_gates", "error", "eval gate policy must be an object", "policies.eval_gates"))
        return issues

    def section_fingerprints(self, bundle):
        policies = bundle.get("policies") if isinstance(bundle.get("policies"), dict) else {}
        return {section: self.fingerprint(policy) for section, policy in policies.items()}

    def preview(self, data=None):
        data = data if isinstance(data, dict) else {}
        proposed = data.get("bundle") if isinstance(data.get("bundle"), dict) else data
        if not proposed or "policies" not in proposed:
            proposed = self.load_bundle()
        sections = data.get("sections") if isinstance(data.get("sections"), list) else sorted((proposed.get("policies") or {}).keys())
        current = self.current_bundle()
        issues = self.validate(proposed)
        before = self.section_fingerprints(current)
        after = self.section_fingerprints(proposed)
        changes = []
        for section in sections:
            changes.append({
                "section": section,
                "before": before.get(section, ""),
                "after": after.get(section, ""),
                "changed": before.get(section) != after.get(section),
                "active_apply": section in {"gateway", "budgets", "automation"},
            })
        blocking = any(item.get("severity") == "error" for item in issues)
        return {
            "dry_run": True,
            "blocking": blocking,
            "issues": issues,
            "sections": sections,
            "changes": changes,
            "fingerprint": self.fingerprint(proposed),
            "bundle": proposed,
        }

    def append_history(self, action, before, after, actor=None):
        row = {
            "id": self.fingerprint({"action": action, "ts": self.clock(), "after": self.fingerprint(after)})[:16],
            "ts": self.clock(),
            "action": action,
            "before_fingerprint": self.fingerprint(before),
            "after_fingerprint": self.fingerprint(after),
            "before": before,
            "after": after,
            "actor": actor if isinstance(actor, dict) else {},
        }
        path = Path(self.history_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def history(self, limit=20):
        path = Path(self.history_file())
        if not path.exists():
            return []
        rows = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-int(limit or 20):]:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
        except OSError:
            return []
        return list(reversed(rows))

    def apply_active_sections(self, bundle, sections):
        policies = bundle.get("policies") if isinstance(bundle.get("policies"), dict) else {}
        if "gateway" in sections and isinstance(policies.get("gateway"), dict):
            self.write_json(self.gateway_policy_file, policies["gateway"])
        if "budgets" in sections and isinstance(policies.get("budgets"), dict):
            self.write_json(self.budget_file, policies["budgets"])
        if "automation" in sections and isinstance(policies.get("automation"), dict):
            self.write_json(self.automation_rules_file, policies["automation"])

    def apply(self, data=None):
        data = data if isinstance(data, dict) else {}
        preview = self.preview(data)
        if preview.get("blocking"):
            raise ValueError("policy bundle has blocking validation errors")
        before = self.load_bundle()
        bundle = preview["bundle"]
        sections = preview["sections"]
        self.save_bundle(bundle)
        self.apply_active_sections(bundle, sections)
        history = self.append_history("policy.apply", before, bundle, actor=data.get("actor"))
        self.append_audit("policy.apply", actor=data.get("actor") or {}, outcome="completed", permission="policy_admin", request={"sections": sections, "fingerprint": preview.get("fingerprint")}, status=200)
        return {"applied": True, "preview": preview, "history": history, "bundle_file": str(self.policy_file())}

    def rollback(self, data=None):
        data = data if isinstance(data, dict) else {}
        version_id = str(data.get("version_id") or "").strip()
        rows = self.history(limit=100)
        row = next((item for item in rows if item.get("id") == version_id), rows[0] if rows else None)
        if not row:
            raise ValueError("no policy history is available for rollback")
        before = self.load_bundle()
        bundle = row.get("before") if isinstance(row.get("before"), dict) else {}
        if not bundle:
            raise ValueError("selected policy history entry cannot be rolled back")
        sections = data.get("sections") if isinstance(data.get("sections"), list) else sorted((bundle.get("policies") or {}).keys())
        issues = self.validate(bundle)
        if any(item.get("severity") == "error" for item in issues):
            raise ValueError("rollback bundle has blocking validation errors")
        self.save_bundle(bundle)
        self.apply_active_sections(bundle, sections)
        history = self.append_history("policy.rollback", before, bundle, actor=data.get("actor"))
        self.append_audit("policy.rollback", actor=data.get("actor") or {}, outcome="completed", permission="policy_admin", request={"sections": sections, "version_id": row.get("id")}, status=200)
        return {"rolled_back": True, "source": row, "history": history, "bundle": bundle}

    def payload(self):
        bundle = self.load_bundle()
        preview = self.preview({"bundle": bundle})
        current = self.current_bundle()
        return {
            "bundle": bundle,
            "current": current,
            "preview": preview,
            "history": self.history(),
            "bundle_file": str(self.policy_file()),
            "history_file": str(self.history_file()),
        }
