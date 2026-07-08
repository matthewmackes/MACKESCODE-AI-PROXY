"""Local Claude proxy process, reload, and registry-sync helpers."""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


class ProxyProcessService:
    """Owns local proxy lifecycle and registry synchronization checks."""

    def __init__(
        self,
        *,
        proxy_host,
        proxy_port,
        port_open,
        request_json,
        proxy_capabilities_raw,
        model_config_fingerprint,
        same_model_config_fingerprint,
        all_models,
        base_url,
        write_token,
        default_text_model,
        token_file,
        model_config_file,
        cost_file,
        budget_file,
        log_file,
        proxy_script,
        executable=None,
        env=None,
        run_func=subprocess.run,
        check_output_func=subprocess.check_output,
        popen_func=subprocess.Popen,
        kill_func=os.kill,
        sleep_func=None,
        devnull=subprocess.DEVNULL,
        proxy_in_sync_func=None,
    ):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.port_open = port_open
        self.request_json = request_json
        self.proxy_capabilities_raw = proxy_capabilities_raw
        self.model_config_fingerprint = model_config_fingerprint
        self.same_model_config_fingerprint = same_model_config_fingerprint
        self.all_models = all_models
        self.base_url = base_url
        self.write_token = write_token
        self.default_text_model = default_text_model
        self.token_file = token_file
        self.model_config_file = model_config_file
        self.cost_file = cost_file
        self.budget_file = budget_file
        self.log_file = log_file
        self.proxy_script = proxy_script
        self.executable = executable or sys.executable
        self.env = env if env is not None else os.environ
        self.run_func = run_func
        self.check_output_func = check_output_func
        self.popen_func = popen_func
        self.kill_func = kill_func
        self.sleep_func = sleep_func
        self.devnull = devnull
        self.proxy_in_sync_func = proxy_in_sync_func

    def value(self, item):
        return item() if callable(item) else item

    def host(self):
        return self.value(self.proxy_host)

    def port(self):
        return int(self.value(self.proxy_port))

    def models(self):
        return list(self.value(self.all_models))

    def proxy_url(self, path):
        return "http://%s:%d%s" % (self.host(), self.port(), path)

    def capabilities_raw(self):
        try:
            return self.request_json(self.proxy_url("/v1/claude-do/capabilities"), payload=None, timeout=2, method="GET")
        except Exception as exc:
            return 599, {"error": str(exc)}

    def in_sync(self):
        if not self.port_open(self.host(), self.port()):
            return False, {"reason": "proxy is not listening"}
        status, payload = self.proxy_capabilities_raw()
        expected_base = str(self.value(self.base_url)).rstrip("/")
        actual_base = str(payload.get("base_url", "")).rstrip("/") if isinstance(payload, dict) else ""
        actual_models = payload.get("models") if isinstance(payload, dict) else []
        expected_fingerprint = self.model_config_fingerprint()
        model_state = payload.get("model_config_state") if isinstance(payload, dict) else {}
        actual_fingerprint = model_state.get("fingerprint") if isinstance(model_state, dict) else {}
        registry_seen = (
            isinstance(model_state, dict)
            and model_state.get("loaded")
            and not model_state.get("stale")
            and self.same_model_config_fingerprint(expected_fingerprint, actual_fingerprint)
        )
        expected_models = self.models()
        ok = (
            status < 400
            and isinstance(payload, dict)
            and payload.get("provider") == "matts-value-set"
            and actual_base == expected_base
            and actual_models == expected_models
            and registry_seen
        )
        reason = "in sync" if ok else "proxy config differs from GUI registry"
        if isinstance(model_state, dict) and model_state.get("stale"):
            reason = "proxy has not reloaded the latest model registry file"
        elif isinstance(model_state, dict) and model_state.get("last_error"):
            reason = "proxy model registry load failed: %s" % model_state.get("last_error")
        return ok, {
            "reason": reason,
            "status": status,
            "capabilities": payload,
            "expected_models": expected_models,
            "expected_base_url": expected_base,
            "expected_model_config": expected_fingerprint,
        }

    def stop(self):
        tmux_name = self.env.get("MATTS_VALUE_SET_TMUX_SESSION", "matts-value-set-proxy")
        self.run_func(["tmux", "kill-session", "-t", tmux_name], stdout=self.devnull, stderr=self.devnull, check=False)
        for args in (
            ["lsof", "-tiTCP:%d" % self.port(), "-sTCP:LISTEN"],
            ["fuser", "-n", "tcp", str(self.port())],
        ):
            try:
                found = self.check_output_func(args, text=True, stderr=self.devnull).split()
            except (OSError, subprocess.SubprocessError):
                continue
            for pid in found:
                try:
                    self.kill_func(int(pid), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
            if found:
                if self.sleep_func:
                    self.sleep_func(0.4)
                break

    def start_if_needed(self, force=False):
        in_sync, _ = self.in_sync()
        if in_sync and not force:
            return
        if force and self.port_open(self.host(), self.port()):
            try:
                self.request_json(self.proxy_url("/v1/claude-do/reload"), {})
                in_sync, _ = self.in_sync()
                if in_sync:
                    return
            except Exception:
                pass
        if self.port_open(self.host(), self.port()):
            self.stop()
        self.write_token()
        cmd = [
            self.executable,
            str(Path(self.value(self.proxy_script))),
            "--provider",
            "matts-value-set",
            "--default-model",
            self.default_text_model(),
            "--host",
            self.host(),
            "--port",
            str(self.port()),
            "--token-file",
            str(self.token_file()),
            "--base-url",
            str(self.value(self.base_url)),
            "--model-config-file",
            str(self.model_config_file()),
            "--models",
            json.dumps(self.models()),
            "--cost-file",
            str(self.cost_file()),
            "--budget-file",
            str(self.budget_file()),
            "--log-file",
            str(self.log_file()),
        ]
        self.popen_func(cmd, stdout=self.devnull, stderr=self.devnull, start_new_session=True)
        for _ in range(50):
            if self.port_open(self.host(), self.port()):
                return
            if self.sleep_func:
                self.sleep_func(0.1)
        raise RuntimeError("proxy did not start on %s:%d" % (self.host(), self.port()))

    def sync_payload(self, force=False):
        start_error = ""
        try:
            self.start_if_needed(force=force)
        except Exception as exc:
            start_error = str(exc)
        in_sync, details = self.in_sync()
        if start_error:
            details["start_error"] = start_error
        return {
            "listening": self.port_open(self.host(), self.port()),
            "in_sync": in_sync,
            "host": self.host(),
            "port": self.port(),
            "url": "http://%s:%d" % (self.host(), self.port()),
            "details": details,
        }

    def registry_sync_issue_for_model(self, model):
        proxy_in_sync = self.proxy_in_sync_func or self.in_sync
        in_sync, details = proxy_in_sync()
        if in_sync:
            return None
        details = details if isinstance(details, dict) else {}
        caps = details.get("capabilities") if isinstance(details.get("capabilities"), dict) else {}
        proxy_models = caps.get("models") if isinstance(caps.get("models"), list) else []
        registry_state = caps.get("model_config_state") if isinstance(caps.get("model_config_state"), dict) else {}
        reason = details.get("reason") or "proxy registry is not synchronized"
        selected_loaded = model in proxy_models
        blocking = not selected_loaded
        message = (
            "The selected model '%s' is not loaded by the Claude Code proxy yet. %s. "
            "Use Sync Proxy from Console or wait for the registry reload to finish before sending."
        ) % (model, reason) if blocking else (
            "The proxy registry needs attention (%s), but the selected model '%s' is already loaded and the request can continue."
        ) % (reason, model)
        return {
            "ok": False,
            "blocking": blocking,
            "message": message,
            "reason": reason,
            "selected_model": model,
            "selected_model_loaded": selected_loaded,
            "proxy_models": proxy_models,
            "registry_state": registry_state,
            "expected_models": details.get("expected_models") or [],
            "expected_model_config": details.get("expected_model_config") or {},
        }
