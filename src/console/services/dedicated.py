"""DigitalOcean Dedicated Inference lifecycle orchestration."""
import datetime
import json
import time
from http import HTTPStatus
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class DedicatedInferenceService:
    """Owns Dedicated Inference state, registry integration, and chat routing."""

    active_states = {"new", "creating", "provisioning", "active", "idle_warning", "draining", "cooldown", "tearing_down"}

    def __init__(
        self,
        default_config,
        steps,
        config_file,
        events_file,
        tail_jsonl,
        digitalocean_token,
        do_request,
        load_model_registry,
        save_model_registry,
        refresh_model_globals,
        models_payload,
        digitalocean_health_snapshot,
        serverless_chat_completion,
        active_text_models,
        default_text_model,
        clock=None,
    ):
        self.default_config = dict(default_config)
        self.steps = list(steps)
        self.config_file = config_file
        self.events_file = events_file
        self.tail_jsonl = tail_jsonl
        self.digitalocean_token = digitalocean_token
        self.do_request = do_request
        self.load_model_registry = load_model_registry
        self.save_model_registry = save_model_registry
        self.refresh_model_globals = refresh_model_globals
        self.models_payload = models_payload
        self.digitalocean_health_snapshot = digitalocean_health_snapshot
        self.serverless_chat_completion = serverless_chat_completion
        self.active_text_models = active_text_models
        self.default_text_model = default_text_model
        self.clock = clock or time.time

    def load_config(self):
        cfg = dict(self.default_config)
        path = self.config_file()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
            except (OSError, ValueError):
                pass
        return cfg

    def save_config(self, cfg):
        merged = dict(self.default_config)
        merged.update(cfg or {})
        path = self.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return merged

    def append_event(self, state, message, severity="info", details=None):
        event = {
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ts": self.clock(),
            "state": state,
            "severity": severity,
            "message": message,
            "details": details or {},
        }
        path = self.events_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def events(self, limit=80):
        rows = self.tail_jsonl(self.events_file(), limit=limit)
        rows.sort(key=lambda item: item.get("ts", 0), reverse=True)
        return rows

    def elapsed_seconds(self, cfg, now=None):
        now = now or self.clock()
        start = float(cfg.get("run_started_at") or 0)
        if not start or cfg.get("state") in {"not_configured", "deleted", "failed"}:
            return 0
        return max(0, int(now - start))

    def cost_usd(self, cfg, now=None):
        hourly = float(cfg.get("price_per_hour") or 0)
        return round((self.elapsed_seconds(cfg, now) / 3600.0) * hourly, 8)

    def clipped_seconds(self, start, end, window_start, window_end):
        left = max(float(start), float(window_start))
        right = min(float(end), float(window_end))
        return max(0.0, right - left)

    def runtime_cost_summary(self, cfg, now=None):
        now = now or self.clock()
        hourly = float(cfg.get("price_per_hour") or 0)
        month_start = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_start = now - 86400
        rows = self.tail_jsonl(self.events_file(), limit=100000)
        rows.sort(key=lambda item: float(item.get("ts") or 0))
        intervals = []
        open_start = None
        for row in rows:
            try:
                ts = float(row.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            state = str(row.get("state") or "")
            message = str(row.get("message") or "")
            if state in {"new", "provisioning", "active"} and (
                "creation accepted" in message.lower() or "state changed" in message.lower()
            ):
                if open_start is None:
                    open_start = ts
            if state in {"deleted", "failed"} or (state == "tearing_down" and "destroying dedicated" in message.lower()):
                if open_start is not None and ts >= open_start:
                    intervals.append((open_start, ts))
                    open_start = None
        if open_start is None and cfg.get("state") in self.active_states:
            open_start = float(cfg.get("run_started_at") or cfg.get("created_at") or 0) or None
        if open_start is not None:
            intervals.append((open_start, now))
        month_seconds = sum(self.clipped_seconds(start, end, month_start, now) for start, end in intervals)
        day_seconds = sum(self.clipped_seconds(start, end, day_start, now) for start, end in intervals)
        return {
            "hourly_usd": hourly,
            "month_seconds": int(month_seconds),
            "last_24h_seconds": int(day_seconds),
            "month_cost_usd": round((month_seconds / 3600.0) * hourly, 8),
            "last_24h_cost_usd": round((day_seconds / 3600.0) * hourly, 8),
            "interval_count": len(intervals),
            "source": "local Dedicated lifecycle events",
        }

    def idle_seconds(self, cfg, now=None):
        now = now or self.clock()
        last = float(cfg.get("last_work_at") or cfg.get("run_started_at") or 0)
        if not last:
            return 0
        return max(0, int(now - last))

    def public_payload(self, cfg):
        now = self.clock()
        clean = dict(cfg)
        if clean.get("access_token"):
            clean["access_token_configured"] = True
            clean["access_token"] = ""
        clean.update({
            "elapsed_seconds": self.elapsed_seconds(cfg, now),
            "idle_seconds": self.idle_seconds(cfg, now),
            "estimated_cost_usd": self.cost_usd(cfg, now),
            "build_age_seconds": max(0, int(now - float(cfg.get("created_at") or now))),
            "status_age_seconds": max(0, int(now - float(cfg.get("last_status_at") or cfg.get("created_at") or now))),
            "token_configured": bool(self.digitalocean_token()),
            "config_file": str(self.config_file()),
            "events_file": str(self.events_file()),
            "steps": self.steps,
        })
        budget = float(cfg.get("daily_budget_usd") or 0)
        clean["budget_percent"] = round((clean["estimated_cost_usd"] / budget) * 100, 2) if budget else 0
        return clean

    def extract_id(self, response):
        if not isinstance(response, dict):
            return ""
        for key in ("dedicated_inference", "inference", "data"):
            item = response.get(key)
            if isinstance(item, dict) and item.get("id"):
                return str(item.get("id"))
        return str(response.get("id") or "")

    def extract_resource(self, response):
        if not isinstance(response, dict):
            return {}
        for key in ("dedicated_inference", "inference", "data"):
            item = response.get(key)
            if isinstance(item, dict):
                return item
        return response

    def endpoint(self, cfg):
        endpoint = cfg.get("public_endpoint_fqdn") if cfg.get("enable_public_endpoint") else cfg.get("private_endpoint_fqdn")
        endpoint = str(endpoint or cfg.get("public_endpoint_fqdn") or cfg.get("private_endpoint_fqdn") or "").strip()
        if endpoint and not endpoint.startswith("http"):
            endpoint = "https://" + endpoint
        return endpoint.rstrip("/")

    def status_message(self, cfg):
        state = cfg.get("state") or "not_configured"
        model = cfg.get("display_name") or cfg.get("model_id") or "Dedicated Inference"
        server_id = cfg.get("inference_id") or "not assigned yet"
        region = cfg.get("region") or "unknown region"
        gpu = cfg.get("accelerator_slug") or "unknown accelerator"
        endpoint = self.endpoint(cfg)
        if state in {"creating", "new", "provisioning", "updating"}:
            step = "DigitalOcean is still building the Dedicated Inference endpoint."
            if not endpoint:
                step += " A public endpoint has not been assigned yet."
            return "%s is not ready yet. %s Current state: %s. Server: %s. Region/GPU: %s / %s. The request was not sent to the model; refresh Dedicated Inference status or wait for the build to reach active." % (model, step, state, server_id, region, gpu)
        if state in {"failed", "error"}:
            return "%s is unavailable because the Dedicated Inference build failed. Server: %s. Last error: %s" % (model, server_id, cfg.get("last_error") or "DigitalOcean did not provide a detailed error.")
        if state in {"deleted", "tearing_down", "not_configured"}:
            return "%s is not available because the Dedicated Inference instance is %s. Build a server before selecting this model." % (model, state)
        if not endpoint:
            return "%s is marked %s, but no endpoint is available yet. Server: %s. Refresh status before retrying." % (model, state, server_id)
        if not cfg.get("access_token"):
            return "%s has an endpoint, but the access token has not been issued yet. Server: %s. Refresh status before retrying." % (model, server_id)
        return "%s is not ready for requests. Current state: %s. Server: %s." % (model, state, server_id)

    def not_ready_payload(self, cfg, requested_model):
        lifecycle = self.public_payload(cfg)
        message = self.status_message(cfg)
        do_health = self.digitalocean_health_snapshot()
        state = lifecycle.get("state")
        if state in {"failed", "error"}:
            next_step = "Rebuild Dedicated Inference with another available GPU or region, or select a Serverless model."
        elif state in {"deleted", "tearing_down", "not_configured"}:
            next_step = "Build a Dedicated Inference server before selecting this model."
        else:
            next_step = "Wait for DigitalOcean to report active, then the app will register and enable the Dedicated model globally."
        return {
            "error": message,
            "message": message,
            "dedicated": lifecycle,
            "digitalocean": do_health,
            "lifecycle": {
                "requested_model": requested_model,
                "state": lifecycle.get("state"),
                "server_id": lifecycle.get("inference_id"),
                "region": lifecycle.get("region"),
                "model_slug": lifecycle.get("model_slug"),
                "accelerator_slug": lifecycle.get("accelerator_slug"),
                "endpoint_ready": bool(self.endpoint(cfg)),
                "access_token_ready": bool(cfg.get("access_token")),
                "build_age_seconds": lifecycle.get("build_age_seconds"),
                "status_age_seconds": lifecycle.get("status_age_seconds"),
                "last_error": lifecycle.get("last_error") or "",
                "next_step": next_step,
            },
        }

    def model_entry(self, cfg, enabled=None):
        hourly = float(cfg.get("price_per_hour") or 0)
        endpoint = self.endpoint(cfg)
        active = cfg.get("state") == "active" and bool(endpoint)
        if enabled is None:
            enabled = active
        return {
            "id": cfg.get("model_id") or "dedicated-inference",
            "display_name": cfg.get("display_name") or "Dedicated Inference",
            "type": "text",
            "provider": "DigitalOcean Dedicated",
            "enabled": bool(enabled),
            "aliases": ["dedicated", "dedicated-inference"],
            "pricing": {"input": 0, "output": 0, "hourly": hourly},
            "context_window": int(cfg.get("context_window") or 0),
            "state": cfg.get("state") or "not_configured",
            "endpoint": endpoint,
            "inference_id": cfg.get("inference_id") or "",
            "dedicated": {
                "managed": True,
                "server_id": cfg.get("inference_id") or "",
                "state": cfg.get("state") or "not_configured",
                "region": cfg.get("region") or "",
                "model_slug": cfg.get("model_slug") or "",
                "accelerator_slug": cfg.get("accelerator_slug") or "",
                "scale": int(cfg.get("scale") or 1),
                "endpoint": endpoint,
                "hourly_usd": hourly,
            },
        }

    def register_model(self, cfg, enabled=None):
        entry = self.model_entry(cfg, enabled=enabled)
        models = self.load_model_registry(include_disabled=True)
        existing = next((m for m in models if m.get("id") == entry["id"]), None)
        models = [m for m in models if m.get("id") != entry["id"]]
        models.append(entry)
        self.save_model_registry(models)
        self.refresh_model_globals()
        if existing != entry:
            self.append_event("registering_model", "Updated Dedicated model registry entry", "success", {"model_id": entry["id"], "enabled": entry["enabled"], "state": entry.get("state")})
        return entry

    def remove_model(self, cfg):
        model_id = cfg.get("model_id") or "dedicated-inference"
        models = [m for m in self.load_model_registry(include_disabled=True) if m.get("id") != model_id]
        self.save_model_registry(models)
        self.refresh_model_globals()
        self.append_event("tearing_down", "Removed Dedicated model from global registry", "warning", {"model_id": model_id})

    def preflight(self, data=None):
        cfg = self.load_config()
        cfg.update({k: v for k, v in (data or {}).items() if k in self.default_config})
        errors = []
        warnings = []
        if not self.digitalocean_token():
            errors.append("Set DIGITALOCEAN_TOKEN or DIGITALOCEAN_TOKEN_FILE for Dedicated Inference automation.")
        for key, label in (("name", "Name"), ("region", "Region"), ("vpc_uuid", "VPC UUID"), ("model_slug", "Model slug"), ("model_provider", "Model provider"), ("accelerator_slug", "Accelerator slug")):
            if not str(cfg.get(key) or "").strip():
                errors.append("%s is required." % label)
        if cfg.get("region") not in {"atl1", "nyc2", "tor1"}:
            warnings.append("DigitalOcean currently documents Dedicated Inference regions as atl1, nyc2, and tor1.")
        budget = float(cfg.get("daily_budget_usd") or 0)
        hourly = float(cfg.get("price_per_hour") or 0)
        if budget and hourly and hourly > budget:
            warnings.append("Selected hourly cost exceeds the configured daily budget.")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "config": self.public_payload(cfg)}

    def update_from_resource(self, cfg, resource):
        status = str(resource.get("status") or cfg.get("state") or "provisioning")
        endpoints = resource.get("endpoints") if isinstance(resource.get("endpoints"), dict) else {}
        cfg["raw"] = resource
        cfg["last_status_at"] = self.clock()
        latest_public = endpoints.get("public_endpoint_fqdn") or resource.get("public_endpoint_fqdn") or ""
        latest_private = endpoints.get("private_endpoint_fqdn") or resource.get("private_endpoint_fqdn") or ""
        cfg["public_endpoint_fqdn"] = latest_public or (cfg.get("public_endpoint_fqdn") if status in {"active", "ready"} else "")
        cfg["private_endpoint_fqdn"] = latest_private or (cfg.get("private_endpoint_fqdn") if status in {"active", "ready"} else "")
        if status in {"active", "ready"}:
            cfg["state"] = "active"
            if not cfg.get("run_started_at"):
                cfg["run_started_at"] = self.clock()
            if not cfg.get("last_work_at"):
                cfg["last_work_at"] = cfg["run_started_at"]
        elif status in {"deleting", "deleted"}:
            cfg["state"] = "tearing_down" if status == "deleting" else "deleted"
        elif status == "error":
            cfg["state"] = "failed"
            cfg["last_error"] = resource.get("error") or "DigitalOcean reported error state"
        elif status:
            cfg["state"] = status
        issue = self.resource_issue(resource)
        if issue:
            cfg["state"] = "failed"
            cfg["last_error"] = issue
        elif str(cfg.get("last_error") or "").startswith("DigitalOcean marked "):
            cfg["last_error"] = ""
        return cfg

    def resource_issue(self, resource):
        if not isinstance(resource, dict):
            return ""
        specs = []
        for key in ("pending_deployment_spec", "deployment_spec", "current_deployment_spec", "spec"):
            if isinstance(resource.get(key), dict):
                specs.append(resource[key])
        for spec in specs:
            spec_state = str(spec.get("status") or spec.get("state") or "").strip().lower()
            for deployment in spec.get("model_deployments") or []:
                if not isinstance(deployment, dict):
                    continue
                model_slug = deployment.get("model_slug") or deployment.get("provider_model_id") or "model"
                for accelerator in deployment.get("accelerators") or []:
                    if not isinstance(accelerator, dict):
                        continue
                    state = str(accelerator.get("status") or accelerator.get("state") or "").strip().lower()
                    if state in {"invalid", "error", "failed"}:
                        if spec_state in {"", "pending", "provisioning"} and not accelerator.get("accelerator_id"):
                            continue
                        slug = accelerator.get("accelerator_slug") or accelerator.get("accelerator_id") or "accelerator"
                        return "DigitalOcean marked %s for %s as %s. Rebuild with another available GPU or region." % (slug, model_slug, state)
        return ""

    def status_payload(self, poll=True):
        cfg = self.load_config()
        token = self.digitalocean_token()
        if poll and token and cfg.get("inference_id") and cfg.get("state") not in {"deleted", "not_configured"}:
            status, response = self.do_request("/v2/dedicated-inferences/%s" % quote(str(cfg["inference_id"]), safe=""), token, method="GET")
            if status < 400:
                previous = cfg.get("state")
                cfg = self.update_from_resource(cfg, self.extract_resource(response))
                if cfg.get("state") != previous:
                    self.append_event(cfg.get("state"), "DigitalOcean state changed to %s" % cfg.get("state"), "info", {"previous": previous})
                if cfg.get("state") == "active" and not cfg.get("access_token"):
                    cfg, _ = self.create_token(cfg)
                if cfg.get("inference_id") and cfg.get("state") not in {"deleted", "not_configured", "tearing_down"}:
                    self.register_model(cfg)
                self.save_config(cfg)
            else:
                cfg["last_error"] = json.dumps(response)[:1000]
                self.save_config(cfg)
                self.append_event("status", "Failed to refresh Dedicated status", "error", {"status": status, "response": response})
        return {"dedicated": self.public_payload(cfg), "events": self.events(), "models": self.models_payload(), "digitalocean": self.digitalocean_health_snapshot()}

    def create_token(self, cfg):
        token = self.digitalocean_token()
        if not token or not cfg.get("inference_id"):
            return cfg, None
        status, response = self.do_request("/v2/dedicated-inferences/%s/tokens" % quote(str(cfg["inference_id"]), safe=""), token, {"name": "matts-console"}, method="POST")
        if status < 400:
            item = self.extract_resource(response)
            token_value = item.get("token")
            if isinstance(token_value, dict):
                token_value = token_value.get("value") or token_value.get("access_key") or token_value.get("token")
            cfg["access_token"] = token_value or item.get("access_key") or item.get("value") or cfg.get("access_token") or ""
            self.append_event("token_issuing", "Dedicated access token created", "success")
        else:
            self.append_event("token_issuing", "Dedicated access token creation failed", "warning", {"status": status, "response": response})
        return cfg, {"status": status, "response": response}

    def build(self, data):
        data = data or {}
        cfg = self.load_config()
        for key in self.default_config:
            if key in data:
                cfg[key] = data[key]
        cfg["scale"] = max(1, int(cfg.get("scale") or 1))
        cfg["price_per_hour"] = float(cfg.get("price_per_hour") or 0)
        cfg["daily_budget_usd"] = float(cfg.get("daily_budget_usd") or 0)
        preflight = self.preflight(cfg)
        self.append_event("preflight", "Checking DigitalOcean permissions and required fields", "info", {"ok": preflight["ok"]})
        if not preflight["ok"]:
            cfg["state"] = "failed"
            cfg["last_error"] = "; ".join(preflight["errors"])
            self.save_config(cfg)
            return HTTPStatus.BAD_REQUEST, {"error": cfg["last_error"], "preflight": preflight, "dedicated": self.public_payload(cfg)}
        cfg["state"] = "creating"
        cfg["created_at"] = self.clock()
        cfg["run_started_at"] = 0
        cfg["last_work_at"] = 0
        cfg["last_error"] = ""
        self.save_config(cfg)
        self.append_event("planning", "Build plan accepted", "info", {"region": cfg["region"], "model_slug": cfg["model_slug"], "accelerator_slug": cfg["accelerator_slug"]})
        payload = {
            "spec": {
                "version": int(cfg.get("version") or 1),
                "name": cfg["name"],
                "region": cfg["region"],
                "vpc": {"uuid": cfg["vpc_uuid"]},
                "enable_public_endpoint": bool(cfg.get("enable_public_endpoint")),
                "model_deployments": [{
                    "name": cfg.get("deployment_name") or "primary",
                    "model_slug": cfg["model_slug"],
                    "model_provider": cfg["model_provider"],
                    "accelerators": [{
                        "scale": int(cfg.get("scale") or 1),
                        "type": cfg.get("accelerator_type") or "gpu",
                        "accelerator_slug": cfg["accelerator_slug"],
                    }],
                }],
            },
        }
        self.append_event("creating", "Requesting Dedicated Inference capacity", "info", {"payload": payload})
        status, response = self.do_request("/v2/dedicated-inferences", self.digitalocean_token(), payload, method="POST", timeout=120)
        cfg["raw"] = response
        if status >= 400:
            cfg["state"] = "failed"
            cfg["last_error"] = json.dumps(response)[:1200]
            self.save_config(cfg)
            self.append_event("failed", "DigitalOcean rejected Dedicated build", "error", {"status": status, "response": response})
            return status, {"error": cfg["last_error"], "response": response, "dedicated": self.public_payload(cfg)}
        cfg["inference_id"] = self.extract_id(response)
        create_token = response.get("token") if isinstance(response, dict) and isinstance(response.get("token"), dict) else {}
        if create_token.get("value"):
            cfg["access_token"] = create_token.get("value")
        cfg["state"] = "provisioning"
        self.save_config(cfg)
        self.register_model(cfg, enabled=False)
        self.append_event("provisioning", "Dedicated Inference creation accepted by DigitalOcean", "success", {"inference_id": cfg.get("inference_id"), "status": status})
        if cfg.get("inference_id") and not cfg.get("access_token"):
            cfg, _ = self.create_token(cfg)
            self.save_config(cfg)
        return HTTPStatus.ACCEPTED, self.status_payload(poll=True)

    def teardown(self, data=None):
        cfg = self.load_config()
        self.remove_model(cfg)
        cfg["state"] = "tearing_down"
        cfg["last_error"] = ""
        self.save_config(cfg)
        token = self.digitalocean_token()
        status = HTTPStatus.ACCEPTED
        response = {"ok": True, "note": "No Dedicated inference id was configured."}
        if token and cfg.get("inference_id"):
            self.append_event("tearing_down", "Destroying Dedicated Inference immediately", "warning", {"inference_id": cfg["inference_id"]})
            status, response = self.do_request("/v2/dedicated-inferences/%s" % quote(str(cfg["inference_id"]), safe=""), token, method="DELETE", timeout=60)
        if int(status) >= 400:
            cfg["state"] = "failed"
            cfg["last_error"] = json.dumps(response)[:1200]
            self.append_event("failed", "Dedicated teardown failed", "error", {"status": int(status), "response": response})
        else:
            cfg["state"] = "deleted"
            cfg["inference_id"] = ""
            cfg["access_token"] = ""
            cfg["public_endpoint_fqdn"] = ""
            cfg["private_endpoint_fqdn"] = ""
            cfg["run_started_at"] = 0
            cfg["last_work_at"] = 0
            self.append_event("deleted", "Dedicated model removed and teardown requested", "success", {"response": response})
        self.save_config(cfg)
        return status, self.status_payload(poll=False)

    def policy(self, data):
        cfg = self.load_config()
        for key in ("daily_budget_usd", "warning_threshold", "cooldown_threshold", "idle_warning_seconds", "idle_teardown_seconds", "auto_rebuild", "fallback_model"):
            if key in data:
                cfg[key] = data[key]
        cfg["daily_budget_usd"] = float(cfg.get("daily_budget_usd") or 0)
        cfg["warning_threshold"] = float(cfg.get("warning_threshold") or 0.8)
        cfg["cooldown_threshold"] = float(cfg.get("cooldown_threshold") or 0.95)
        cfg["idle_warning_seconds"] = int(cfg.get("idle_warning_seconds") or 300)
        cfg["idle_teardown_seconds"] = int(cfg.get("idle_teardown_seconds") or 600)
        self.save_config(cfg)
        self.append_event("policy", "Dedicated policy updated", "success", {"policy": self.public_payload(cfg)})
        return HTTPStatus.OK, self.status_payload(poll=False)

    def discovery(self, path):
        token = self.digitalocean_token()
        if not token:
            return HTTPStatus.BAD_REQUEST, {"error": "DigitalOcean token is not configured"}
        status, response = self.do_request(path, token, method="GET", timeout=60)
        return status, response

    def is_model(self, model):
        cfg = self.load_config()
        return bool(model and model == cfg.get("model_id"))

    def chat_completion(self, data, cfg):
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        fallback_model = cfg.get("fallback_model")
        fallback = fallback_model if fallback_model in self.active_text_models() else self.default_text_model()
        endpoint = self.endpoint(cfg)
        if cfg.get("state") != "active" or not endpoint or not cfg.get("access_token"):
            payload = self.not_ready_payload(cfg, data.get("model"))
            self.append_event("waiting", "Dedicated request blocked because endpoint is not ready", "warning", payload.get("lifecycle"))
            return HTTPStatus.CONFLICT, payload
        payload = {
            "model": cfg.get("model_slug") or data.get("model"),
            "messages": messages,
            "max_tokens": max(1, min(8192, int(data.get("max_tokens") or 512))),
            "stream": False,
        }
        if "qwen3" in str(cfg.get("model_slug") or "").lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if data.get("temperature") not in (None, ""):
            payload["temperature"] = float(data["temperature"])
        req = Request(endpoint + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={
            "content-type": "application/json",
            "authorization": "Bearer " + cfg.get("access_token"),
            "user-agent": "matts-console/1.0",
        }, method="POST")
        try:
            with urlopen(req, timeout=240) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8", errors="replace"))
            except ValueError:
                error = {"error": exc.reason}
            self.append_event("fallback", "Dedicated request failed; routed chat to Serverless", "warning", {"status": exc.code, "response": error})
            status, fallback_payload = self.serverless_chat_completion(data, fallback, allow_unregistered=True)
            if isinstance(fallback_payload, dict):
                fallback_payload["routing"] = {"requested": data.get("model"), "used": fallback, "reason": "Dedicated request failed", "backend": "serverless"}
            return status, fallback_payload
        except URLError as exc:
            self.append_event("fallback", "Dedicated endpoint unreachable; routed chat to Serverless", "warning", {"error": str(exc.reason)})
            status, fallback_payload = self.serverless_chat_completion(data, fallback, allow_unregistered=True)
            if isinstance(fallback_payload, dict):
                fallback_payload["routing"] = {"requested": data.get("model"), "used": fallback, "reason": "Dedicated endpoint unreachable", "backend": "serverless"}
            return status, fallback_payload
        text = ""
        choices = raw.get("choices") if isinstance(raw, dict) else []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            text = message.get("content") or choices[0].get("text") or ""
        cfg["last_work_at"] = self.clock()
        self.save_config(cfg)
        self.append_event("active", "Dedicated served chat request", "success", {"model": cfg.get("model_id")})
        usage = raw.get("usage") if isinstance(raw, dict) else {}
        return HTTPStatus.OK, {"text": text, "raw": raw, "usage": usage or {}, "cost": {"total_cost_usd": self.cost_usd(cfg)}, "routing": {"requested": data.get("model"), "used": cfg.get("model_id"), "backend": "dedicated"}}
