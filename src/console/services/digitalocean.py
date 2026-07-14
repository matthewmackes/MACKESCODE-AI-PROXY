"""DigitalOcean platform, account, and balance health helpers."""
import time

from src.console.services.operational_store import OperationalStore


class DigitalOceanHealthService:
    """Builds the DigitalOcean health snapshot shown in Console and lifecycle UI."""

    def __init__(self, public_json_url, do_get, digitalocean_token, cache=None, clock=None, load_dedicated_config=None, operational_store=None):
        self.public_json_url = public_json_url
        self.do_get = do_get
        self.digitalocean_token = digitalocean_token
        self.cache = cache if cache is not None else {"ts": 0, "payload": None}
        self.clock = clock or time.time
        self.load_dedicated_config = load_dedicated_config
        self.operational_store = operational_store if operational_store is not None else OperationalStore(clock=self.clock)

    def mask_email(self, value):
        email = str(value or "")
        if "@" not in email:
            return email
        name, domain = email.split("@", 1)
        if len(name) <= 2:
            masked = name[:1] + "*"
        else:
            masked = name[:2] + "***" + name[-1:]
        return masked + "@" + domain

    def platform_status(self):
        status_code, status_payload = self.public_json_url("https://status.digitalocean.com/api/v2/status.json")
        incidents_code, incidents_payload = self.public_json_url("https://status.digitalocean.com/api/v2/incidents/unresolved.json")
        result = {
            "reachable": status_code < 400,
            "indicator": "unknown",
            "description": "DigitalOcean status unavailable",
            "updated_at": "",
            "unresolved_incidents": [],
            "errors": [],
        }
        if status_code < 400:
            page = status_payload.get("page") if isinstance(status_payload, dict) else {}
            status = status_payload.get("status") if isinstance(status_payload, dict) else {}
            page = page if isinstance(page, dict) else {}
            status = status if isinstance(status, dict) else {}
            result.update({
                "indicator": status.get("indicator") or "unknown",
                "description": status.get("description") or "unknown",
                "updated_at": page.get("updated_at") or "",
            })
        else:
            result["errors"].append({"status_status": status_code, "response": status_payload})
        if incidents_code < 400:
            incidents = incidents_payload.get("incidents") if isinstance(incidents_payload, dict) else []
            incidents = incidents if isinstance(incidents, list) else []
            result["unresolved_incidents"] = [{
                "name": item.get("name"),
                "status": item.get("status"),
                "impact": item.get("impact"),
                "updated_at": item.get("updated_at"),
                "shortlink": item.get("shortlink"),
            } for item in incidents[:5] if isinstance(item, dict)]
        else:
            result["errors"].append({"incidents_status": incidents_code, "response": incidents_payload})
        return result

    def money_value(self, payload, key):
        try:
            return float(payload.get(key) or 0)
        except (TypeError, ValueError, AttributeError):
            return 0.0

    def snapshot(self):
        now = self.clock()
        if self.cache.get("payload") and now - float(self.cache.get("ts") or 0) < 60:
            return self.cache["payload"]
        token = self.digitalocean_token()
        payload = {
            "configured": bool(token),
            "checked_at": now,
            "platform": self.platform_status(),
            "account": None,
            "prepay": None,
            "monitoring": {"configured": False, "metrics": {}, "errors": ["DigitalOcean token is not configured."]},
            "errors": [],
        }
        if not token:
            payload["errors"].append("DigitalOcean token is not configured.")
            try:
                self.operational_store.save_digitalocean_snapshot(payload, source="digitalocean_health")
            except Exception:
                pass
            self.cache.update({"ts": now, "payload": payload})
            return payload
        status, account = self.do_get("/v2/account", token, timeout=20)
        if status < 400:
            acct = account.get("account") if isinstance(account, dict) else {}
            payload["account"] = {
                "status": acct.get("status") or "unknown",
                "status_message": acct.get("status_message") or "",
                "email": self.mask_email(acct.get("email")),
                "email_verified": bool(acct.get("email_verified")),
                "droplet_limit": acct.get("droplet_limit"),
                "floating_ip_limit": acct.get("floating_ip_limit"),
                "team_uuid": acct.get("team_uuid") or "",
            }
        else:
            payload["errors"].append({"account_status": status, "response": account})
        status, balance = self.do_get("/v2/customers/my/balance", token, timeout=20)
        if status < 400:
            account_balance = self.money_value(balance, "account_balance")
            payload["prepay"] = {
                "account_balance": account_balance,
                "month_to_date_balance": self.money_value(balance, "month_to_date_balance"),
                "month_to_date_usage": self.money_value(balance, "month_to_date_usage"),
                "generated_at": balance.get("generated_at") if isinstance(balance, dict) else "",
                "status": "credit_available" if account_balance < 0 else ("payment_due" if account_balance > 0 else "settled"),
            }
        else:
            payload["errors"].append({"balance_status": status, "response": balance})
        payload["monitoring"] = self.monitoring_metrics(token, now)
        try:
            self.operational_store.save_digitalocean_snapshot(payload, source="digitalocean_health")
        except Exception:
            pass
        self.cache.update({"ts": now, "payload": payload})
        return payload

    def monitoring_host_id(self):
        if self.load_dedicated_config is None:
            return "", {}
        try:
            cfg = self.load_dedicated_config()
        except Exception:
            return "", {}
        cfg = cfg if isinstance(cfg, dict) else {}
        for key in ("server_id", "droplet_id", "host_id", "resource_id"):
            value = str(cfg.get(key) or "").strip()
            if value:
                return value, cfg
        raw = cfg.get("raw") if isinstance(cfg.get("raw"), dict) else {}
        for key in ("server_id", "droplet_id", "host_id", "id"):
            value = str(raw.get(key) or "").strip()
            if value:
                return value, cfg
        return "", cfg

    def monitoring_metrics(self, token, now=None):
        now = float(now if now is not None else self.clock())
        host_id, cfg = self.monitoring_host_id()
        result = {
            "configured": bool(token and host_id),
            "host_id": host_id,
            "checked_at": now,
            "window_seconds": 3600,
            "dedicated_state": cfg.get("state") if isinstance(cfg, dict) else "",
            "metrics": {},
            "errors": [],
            "docs": {
                "droplet_metrics": "https://docs.digitalocean.com/products/monitoring/concepts/metrics/",
                "api": "https://docs.digitalocean.com/reference/api/",
            },
        }
        if not token:
            result["errors"].append("DigitalOcean token is not configured.")
            return result
        if not host_id:
            result["errors"].append("No Dedicated Inference host id is available for Monitoring API queries.")
            return result
        start = int(now - 3600)
        end = int(now)
        metric_paths = {
            "cpu": "/v2/monitoring/metrics/droplet/cpu",
            "memory_available": "/v2/monitoring/metrics/droplet/memory_available",
            "load_1": "/v2/monitoring/metrics/droplet/load_1",
            "bandwidth": "/v2/monitoring/metrics/droplet/bandwidth",
        }
        for metric, path in metric_paths.items():
            status, payload = self.do_get(path, token, {"host_id": host_id, "start": start, "end": end}, timeout=20)
            if status >= 400:
                result["errors"].append({"metric": metric, "status": status, "response": payload})
                continue
            values = self.metric_values(payload)
            result["metrics"][metric] = {
                "samples": len(values),
                "latest": values[-1] if values else None,
                "average": round(sum(values) / len(values), 4) if values else None,
                "raw": payload if len(str(payload)) < 4000 else {"truncated": True},
            }
        return result

    def metric_values(self, payload):
        data = payload.get("data") if isinstance(payload, dict) else {}
        result = data.get("result") if isinstance(data, dict) else []
        values = []
        for series in result if isinstance(result, list) else []:
            for sample in ((series.get("values") or []) if isinstance(series, dict) else []):
                if not isinstance(sample, (list, tuple)) or len(sample) < 2:
                    continue
                try:
                    values.append(float(sample[1]))
                except (TypeError, ValueError):
                    continue
        return values
