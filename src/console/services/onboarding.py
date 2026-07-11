"""First-run onboarding checklist and runtime completion state."""
import json
import os
import time
from pathlib import Path


class OnboardingChecklistService:
    """Build a redacted setup checklist from existing console health signals."""

    def __init__(
        self,
        *,
        state_file,
        project_dir,
        token_file,
        digitalocean_token,
        digitalocean_token_paths,
        active_model_access_key_info,
        port_open,
        proxy_host,
        proxy_port,
        proxy_sync_payload,
        models_payload,
        budget_file,
        auth_enabled,
        role_token_summary,
        rollback_targets_payload,
        dedicated_status_payload,
        serverless_catalog_payload,
        clock=None,
    ):
        self.state_file = state_file
        self.project_dir = project_dir
        self.token_file = token_file
        self.digitalocean_token = digitalocean_token
        self.digitalocean_token_paths = digitalocean_token_paths
        self.active_model_access_key_info = active_model_access_key_info
        self.port_open = port_open
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.proxy_sync_payload = proxy_sync_payload
        self.models_payload = models_payload
        self.budget_file = budget_file
        self.auth_enabled = auth_enabled
        self.role_token_summary = role_token_summary
        self.rollback_targets_payload = rollback_targets_payload
        self.dedicated_status_payload = dedicated_status_payload
        self.serverless_catalog_payload = serverless_catalog_payload
        self.clock = clock or time.time

    def value(self, raw):
        return raw() if callable(raw) else raw

    def read_state(self):
        path = Path(self.value(self.state_file))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        completed = data.get("completed") if isinstance(data.get("completed"), dict) else {}
        return {"completed": completed}

    def write_state(self, state):
        path = Path(self.value(self.state_file))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)

    def complete(self, request):
        request = request if isinstance(request, dict) else {}
        item_id = str(request.get("id") or "").strip()
        if not item_id:
            raise ValueError("onboarding item id is required")
        state = self.read_state()
        completed = state.setdefault("completed", {})
        completed[item_id] = {
            "completed_at": float(self.clock()),
            "actor_id": ((request.get("actor") or {}) if isinstance(request.get("actor"), dict) else {}).get("id") or "",
            "note": str(request.get("note") or "")[:300],
        }
        self.write_state(state)
        return self.payload()

    def payload(self):
        state = self.read_state()
        completed = state.get("completed") or {}
        checks = self.checks(completed)
        incomplete = [row for row in checks if row.get("status") in {"missing", "warning", "failed"} and not row.get("completed")]
        return {
            "generated_at": float(self.clock()),
            "state_file": str(Path(self.value(self.state_file))),
            "first_run": len(completed) == 0 and bool(incomplete),
            "complete": len(incomplete) == 0,
            "summary": {
                "checks": len(checks),
                "passed": len([row for row in checks if row.get("status") == "passed" or row.get("completed")]),
                "incomplete": len(incomplete),
                "warnings": len([row for row in checks if row.get("status") == "warning" and not row.get("completed")]),
            },
            "checks": checks,
            "actions": self.actions(),
            "privacy": "Checklist evidence is redacted. Token values and secret-bearing runtime files are never returned.",
        }

    def item(self, completed, item_id, title, status, detail, action, evidence=None, required=True):
        done = item_id in completed
        return {
            "id": item_id,
            "title": title,
            "status": "passed" if done else status,
            "required": bool(required),
            "completed": done,
            "completed_at": (completed.get(item_id) or {}).get("completed_at") if isinstance(completed.get(item_id), dict) else None,
            "detail": detail,
            "action": action,
            "evidence": evidence or {},
        }

    def checks(self, completed):
        token = Path(self.value(self.token_file))
        key_info = self.safe_call(self.active_model_access_key_info, {})
        do_token = bool(self.safe_call(self.digitalocean_token, ""))
        do_paths = [str(Path(path)) for path in self.safe_call(self.digitalocean_token_paths, [])]
        proxy = self.safe_call(lambda: self.proxy_sync_payload(force=False), {})
        models = self.safe_call(lambda: self.models_payload(refresh_catalog=False), {})
        role_tokens = self.safe_call(self.role_token_summary, {})
        dedicated = self.safe_call(lambda: self.dedicated_status_payload(poll=False), {})
        rollback = self.safe_call(self.rollback_targets_payload, {})
        serverless = self.safe_call(lambda: self.serverless_catalog_payload(force=False), {})
        budget = self.budget_status()
        release = self.release_status()
        proxy_listening = bool(self.safe_call(lambda: self.port_open(self.value(self.proxy_host), self.value(self.proxy_port)), False))
        text_options = models.get("text_model_options") if isinstance(models, dict) else []
        allowed = [row for row in (text_options or []) if row.get("access_status") == "ok" or (row.get("enabled") and not row.get("serverless"))]
        dedicated_state = ((dedicated.get("dedicated") if isinstance(dedicated, dict) else {}) or {}).get("state") or "not_configured"
        runtime_archives = ((rollback.get("summary") if isinstance(rollback, dict) else {}) or {}).get("runtime_archives") or 0
        catalog = serverless.get("catalog") if isinstance(serverless, dict) else {}
        if not isinstance(catalog, dict):
            catalog = {}
        return [
            self.item(completed, "model_access_token", "Model access token", "passed" if key_info.get("configured") or token.exists() else "missing", "Model access key is configured." if key_info.get("configured") or token.exists() else "Create the model access token file before launching proxy requests.", "create_token_file", {"path": str(token), "exists": token.exists(), "source": key_info.get("source") or ("file" if token.exists() else "missing")}),
            self.item(completed, "digitalocean_token", "DigitalOcean token", "passed" if do_token else "warning", "DigitalOcean token is available." if do_token else "DigitalOcean token is optional until billing, Serverless catalog refresh, or Dedicated actions are needed.", "configure_digitalocean_token", {"configured": do_token, "candidate_paths": do_paths}, required=False),
            self.item(completed, "proxy_health", "Proxy health and registry sync", "passed" if proxy_listening and proxy.get("in_sync", proxy.get("listening", False)) else "failed", "Proxy is reachable and registry appears synced." if proxy_listening else "Proxy is offline or registry sync needs attention.", "sync_proxy", {"listening": proxy_listening, "host": self.value(self.proxy_host), "port": self.value(self.proxy_port), "in_sync": bool(proxy.get("in_sync"))}),
            self.item(completed, "model_access_audit", "Model access audit", "passed" if allowed else "warning", "At least one text model is available." if allowed else "Run model access audit so selectors do not show stale models.", "audit_model_access_key", {"available_text_models": len(allowed), "registry_valid": ((models.get("registry_status") or {}) if isinstance(models, dict) else {}).get("valid", False)}),
            self.item(completed, "budget_defaults", "Budget defaults", "passed" if budget["configured"] else "warning", "Budget limits are configured." if budget["configured"] else "Configure daily, monthly, or total budget limits.", "configure_budget", budget),
            self.item(completed, "auth_roles", "Console auth and role tokens", "passed" if self.value(self.auth_enabled) and int(role_tokens.get("count") or 0) > 0 else "warning", "Console auth and role tokens are configured." if int(role_tokens.get("count") or 0) > 0 else "Console owner token works, but scoped role tokens are not configured.", "configure_role_tokens", {"auth_enabled": bool(self.value(self.auth_enabled)), "role_token_count": int(role_tokens.get("count") or 0), "source": role_tokens.get("source") or "config"}),
            self.item(completed, "release_smoke", "Release and V2 browser smoke readiness", "passed" if release["commands_present"] and release["coverage_present"] else "warning", "Release check artifacts and V2 smoke commands are available." if release["coverage_present"] else "Run scripts/release-check.sh to create fresh release and V2 browser smoke evidence.", "run_release_check", release),
            self.item(completed, "runtime_backup", "Runtime-state backup setup", "passed" if int(runtime_archives) > 0 else "warning", "At least one runtime-state archive is discoverable." if int(runtime_archives) > 0 else "Create an initial runtime-state backup before risky changes.", "create_runtime_backup", {"runtime_archives": int(runtime_archives), "procedure": ((rollback.get("procedures") or {}) if isinstance(rollback, dict) else {}).get("runtime_state") or "scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz"}),
            self.item(completed, "dedicated_readiness", "Dedicated Inference readiness", "passed" if dedicated_state in {"active", "ready", "not_configured"} else "warning", "Dedicated state is %s." % dedicated_state, "dedicated_preflight", {"state": dedicated_state}, required=False),
            self.item(completed, "serverless_readiness", "Serverless catalog readiness", "passed" if catalog.get("cached") or catalog.get("fetched_at") or allowed else "warning", "Serverless catalog or available model metadata is present.", "refresh_serverless_catalog", {"cache_status": catalog.get("status") or serverless.get("status") if isinstance(serverless, dict) else "", "available_text_models": len(allowed)}),
        ]

    def budget_status(self):
        path = Path(self.value(self.budget_file))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        configured = any(float(data.get(key) or 0) > 0 for key in ("daily_usd", "monthly_usd", "total_usd"))
        return {"configured": configured, "path": str(path), "keys": sorted([key for key in data if key in {"daily_usd", "monthly_usd", "total_usd"}])}

    def release_status(self):
        root = Path(self.value(self.project_dir))
        commands = ["scripts/release-check.sh", "scripts/v2-browser-smoke.py", "scripts/runtime-state.py"]
        present = [cmd for cmd in commands if (root / cmd).exists()]
        coverage = root / "build" / "coverage" / "coverage.json"
        return {"commands_present": len(present) == len(commands), "commands": present, "coverage_present": coverage.exists(), "coverage_path": str(coverage)}

    def actions(self):
        return {
            "create_token_file": "Write the model access key to the configured token file or run claude-DO.sh --doctor after setting MATTS_VALUE_SET_ACCESS_KEY.",
            "configure_digitalocean_token": "Set DIGITALOCEAN_TOKEN or write it to one of the configured DigitalOcean token files.",
            "sync_proxy": "Use Sync Proxy or run ./claude-DO.sh --restart --doctor.",
            "audit_model_access_key": "Open LLM Management and run key audit.",
            "configure_budget": "Set daily, monthly, or total budget values in System Operations.",
            "configure_role_tokens": "Add scoped role tokens in config/console.json or MATTS_CONSOLE_ROLE_TOKENS_JSON.",
            "run_release_check": "Run ./scripts/release-check.sh from the project root.",
            "create_runtime_backup": "Run scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz.",
            "dedicated_preflight": "Open Inference Hosting Lifecycle and run Dedicated preflight when Dedicated will be used.",
            "refresh_serverless_catalog": "Use Import Serverless Models or run model access audit.",
        }

    def safe_call(self, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            return {"error": str(exc)} if isinstance(fallback, dict) else fallback
