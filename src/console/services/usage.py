"""Usage, cost, budget, and billing report helpers."""
import datetime
import json
import time
from urllib.parse import quote


class UsageService:
    """Build local and DigitalOcean usage reports without HTTP-handler coupling."""

    def __init__(
        self,
        cost_file,
        budget_file,
        tail_jsonl,
        do_get,
        digitalocean_token,
        digitalocean_account_urn,
        digitalocean_health_snapshot,
        load_dedicated_config,
        dedicated_runtime_cost_summary,
        clock=None,
    ):
        self.cost_file = cost_file
        self.budget_file = budget_file
        self.tail_jsonl = tail_jsonl
        self.do_get = do_get
        self.digitalocean_token = digitalocean_token
        self.digitalocean_account_urn = digitalocean_account_urn
        self.digitalocean_health_snapshot = digitalocean_health_snapshot
        self.load_dedicated_config = load_dedicated_config
        self.dedicated_runtime_cost_summary = dedicated_runtime_cost_summary
        self.clock = clock or time.time

    def parse_date(self, value, default):
        try:
            return datetime.date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return default

    def local_usage_report(self, start_date, end_date):
        rows = self.tail_jsonl(self.cost_file(), limit=100000)
        daily = {}
        by_model = {}
        total = 0.0
        for row in rows:
            try:
                day = datetime.datetime.fromtimestamp(float(row.get("ts", 0))).date()
            except (TypeError, ValueError, OSError):
                continue
            if day < start_date or day > end_date:
                continue
            cost = float((row.get("cost") or {}).get("total_cost_usd") or 0.0)
            model = row.get("upstream_model") or row.get("requested_model") or "unknown"
            total += cost
            key = day.isoformat()
            daily[key] = round(daily.get(key, 0.0) + cost, 8)
            by_model[model] = round(by_model.get(model, 0.0) + cost, 8)
        return {
            "total_usd": round(total, 8),
            "daily": [{"date": key, "amount_usd": value} for key, value in sorted(daily.items())],
            "by_model": [{"model": key, "amount_usd": value} for key, value in sorted(by_model.items(), key=lambda item: item[1], reverse=True)],
        }

    def local_usage_since(self, since_ts, now=None):
        now = now or self.clock()
        total = 0.0
        for row in self.tail_jsonl(self.cost_file(), limit=100000):
            try:
                ts = float(row.get("ts", 0))
            except (TypeError, ValueError):
                continue
            if ts < since_ts or ts > now:
                continue
            total += float((row.get("cost") or {}).get("total_cost_usd") or 0.0)
        return round(total, 8)

    def insight_rows(self, insights):
        if not isinstance(insights, dict):
            return []
        for key in ("insights", "billing_insights", "data", "items"):
            rows = insights.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def insight_amount(self, row):
        for key in ("amount", "amount_usd", "cost", "cost_usd", "total", "total_usd"):
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                continue
        return 0.0

    def digitalocean_insights_total(self, token, account_urn, start_date, end_date):
        if not token or not account_urn:
            return None, "missing_account_urn"
        path = "/v2/billing/%s/insights/%s/%s" % (
            quote(account_urn, safe=":"),
            start_date.isoformat(),
            end_date.isoformat(),
        )
        status, payload = self.do_get(path, token, {"per_page": 100, "page": 1}, timeout=30)
        if status >= 400:
            return None, {"status": status, "response": payload}
        total = sum(self.insight_amount(row) for row in self.insight_rows(payload))
        return round(total, 8), "digitalocean_billing_insights"

    def cost_summary_payload(self):
        now = self.clock()
        health = self.digitalocean_health_snapshot()
        prepay = health.get("prepay") if isinstance(health, dict) else {}
        cfg = self.load_dedicated_config()
        dedicated = self.dedicated_runtime_cost_summary(cfg, now)
        local_24h = self.local_usage_since(now - 86400, now)
        token = self.digitalocean_token()
        account_urn = self.digitalocean_account_urn()
        today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
        day_total, day_source = self.digitalocean_insights_total(token, account_urn, today - datetime.timedelta(days=1), today)
        if day_total is None:
            day_total = round(local_24h + dedicated["last_24h_cost_usd"], 8)
            day_source = "local_proxy_plus_dedicated_estimate"
        month_total = None
        if isinstance(prepay, dict) and isinstance(prepay.get("month_to_date_usage"), (int, float)):
            month_total = float(prepay.get("month_to_date_usage"))
        return {
            "checked_at": now,
            "digitalocean_configured": bool(token),
            "account_urn_configured": bool(account_urn),
            "month_to_date_total_usd": month_total,
            "last_24h_total_usd": day_total,
            "last_24h_source": day_source,
            "dedicated_month_to_date_usd": dedicated["month_cost_usd"],
            "dedicated_last_24h_usd": dedicated["last_24h_cost_usd"],
            "dedicated_runtime": dedicated,
            "local_proxy_last_24h_usd": local_24h,
            "digitalocean": {
                "account": health.get("account") if isinstance(health, dict) else None,
                "prepay": prepay,
                "errors": health.get("errors", []) if isinstance(health, dict) else [],
            },
        }

    def digitalocean_report(self, data):
        today = datetime.datetime.fromtimestamp(self.clock(), datetime.timezone.utc).date()
        days = max(1, min(31, int(data.get("days") or 7)))
        start_date = self.parse_date(data.get("start_date"), today - datetime.timedelta(days=days - 1))
        end_date = self.parse_date(data.get("end_date"), today)
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        token = str(data.get("do_token") or "").strip() or self.digitalocean_token()
        account_urn = str(data.get("account_urn") or "").strip() or self.digitalocean_account_urn()
        report = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": (end_date - start_date).days + 1,
            "digitalocean_configured": bool(token),
            "account_urn": account_urn,
            "local_usage": self.local_usage_report(start_date, end_date),
            "balance": None,
            "billing_history": None,
            "insights": None,
            "errors": [],
            "docs": {
                "billing": "https://docs.digitalocean.com/reference/api/reference/billing/",
                "spend_by_date_range": "https://docs.digitalocean.com/platform/billing/spend-by-date-range/",
            },
        }
        if not token:
            report["errors"].append("Set DIGITALOCEAN_TOKEN or DIGITALOCEAN_TOKEN_FILE for DigitalOcean billing data. Required scope: billing:read.")
            return report
        status, balance = self.do_get("/v2/customers/my/balance", token)
        if status < 400:
            report["balance"] = balance
        else:
            report["errors"].append({"balance_status": status, "response": balance})
        status, history = self.do_get("/v2/customers/my/billing_history", token, {"per_page": 50})
        if status < 400:
            report["billing_history"] = history
        else:
            report["errors"].append({"billing_history_status": status, "response": history})
        if account_urn:
            path = "/v2/billing/%s/insights/%s/%s" % (
                quote(account_urn, safe=":"),
                start_date.isoformat(),
                end_date.isoformat(),
            )
            status, insights = self.do_get(path, token, {"per_page": 100, "page": 1})
            if status < 400:
                report["insights"] = insights
            else:
                report["errors"].append({"insights_status": status, "response": insights})
        else:
            report["errors"].append("Set DIGITALOCEAN_ACCOUNT_URN, for example do:team:uuid, to load daily spend insights.")
        return report

    def save_budget(self, data):
        allowed = {}
        for key in ("daily_usd", "monthly_usd", "total_usd"):
            value = data.get(key)
            if value in (None, ""):
                continue
            allowed[key] = float(value)
        path = self.budget_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(allowed, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return allowed
