"""Local automation rules and signed webhook delivery."""
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class AutomationRulesService:
    """Match local operational events to bounded audited actions."""

    ACTION_TYPES = {"create_review", "audit_event", "session_snapshot", "dedicated_event", "webhook", "run_eval"}
    SENSITIVE_PARTS = ("token", "secret", "password", "authorization", "api_key", "access_key", "messages", "prompt", "screen", "raw", "output")
    SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}

    def __init__(self, rules_file, execution_log_file, create_review_item=None, create_session_snapshot=None, append_audit=None, append_dedicated_event=None, run_eval=None, http_post=None, clock=None, uuid_factory=None):
        self.rules_file = rules_file
        self.execution_log_file = execution_log_file
        self.create_review_item = create_review_item or (lambda payload: {"review": payload})
        self.create_session_snapshot = create_session_snapshot or (lambda payload: {"snapshot": payload})
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.append_dedicated_event = append_dedicated_event or (lambda *args, **kwargs: None)
        self.run_eval = run_eval or (lambda payload: {"eval": payload})
        self.http_post = http_post or self.default_http_post
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def path(self):
        path = Path(self.rules_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def log_path(self):
        path = Path(self.execution_log_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def default_config(self):
        return {"schema_version": 1, "rules": []}

    def load_config(self):
        path = self.path()
        if not path.exists():
            return self.default_config()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.default_config()
        return self.normalize_config(data)

    def save_config(self, data, actor=None):
        config = self.normalize_config(data)
        config = self.preserve_redacted_webhook_secrets(config, self.load_config())
        self.path().write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.append_audit("automation.rules.save", actor=actor or {}, outcome="completed", permission="automation_admin", request={"rules": [rule["id"] for rule in config["rules"]]}, status=200)
        return self.redact(config)

    def preserve_redacted_webhook_secrets(self, config, existing):
        existing_rules = {rule.get("id"): rule for rule in (existing.get("rules") or []) if isinstance(rule, dict)}
        for rule in config.get("rules") or []:
            old_rule = existing_rules.get(rule.get("id")) or {}
            old_actions = old_rule.get("actions") if isinstance(old_rule.get("actions"), list) else []
            for index, action in enumerate(rule.get("actions") or []):
                if action.get("type") != "webhook" or action.get("secret") != "[redacted]":
                    continue
                old_action = old_actions[index] if index < len(old_actions) and isinstance(old_actions[index], dict) else {}
                if old_action.get("type") == "webhook" and old_action.get("url") == action.get("url") and old_action.get("secret"):
                    action["secret"] = old_action.get("secret")
        return config

    def normalize_config(self, data):
        data = data if isinstance(data, dict) else {}
        rules = data.get("rules") if isinstance(data.get("rules"), list) else []
        return {"schema_version": 1, "rules": [self.normalize_rule(rule) for rule in rules if isinstance(rule, dict)]}

    def normalize_rule(self, rule):
        rule_id = str(rule.get("id") or "rule_%s" % self.uuid_factory().hex[:8]).strip()
        trigger = rule.get("trigger") if isinstance(rule.get("trigger"), dict) else {}
        actions = rule.get("actions") if isinstance(rule.get("actions"), list) else []
        normalized = {
            "id": rule_id,
            "name": str(rule.get("name") or rule_id).strip(),
            "enabled": bool(rule.get("enabled", True)),
            "trigger": {
                "event": str(trigger.get("event") or "*").strip(),
                "source": str(trigger.get("source") or "").strip(),
                "min_severity": str(trigger.get("min_severity") or "").strip().lower(),
                "field_equals": trigger.get("field_equals") if isinstance(trigger.get("field_equals"), dict) else {},
            },
            "actions": [self.normalize_action(action) for action in actions if isinstance(action, dict)],
        }
        schedule = self.normalize_schedule(trigger, normalized["trigger"])
        if schedule:
            normalized["trigger"]["schedule"] = schedule
        if not normalized["actions"]:
            normalized["actions"] = [{"type": "audit_event", "action": "automation.matched"}]
        return normalized

    def normalize_schedule(self, trigger, normalized_trigger):
        schedule = trigger.get("schedule") if isinstance(trigger.get("schedule"), dict) else {}
        if not schedule:
            return None
        interval = int(schedule.get("interval_seconds") or schedule.get("every_seconds") or 0)
        if interval <= 0:
            raise ValueError("schedule interval_seconds is required")
        interval = max(60, min(2592000, interval))
        event_name = str(schedule.get("event") or normalized_trigger.get("event") or "automation.schedule").strip()
        if event_name == "*":
            event_name = "automation.schedule"
        source = str(schedule.get("source") or normalized_trigger.get("source") or "schedule").strip()
        severity = str(schedule.get("severity") or "medium").strip().lower()
        if severity not in self.SEVERITY_WEIGHT:
            severity = "medium"
        return {
            "enabled": bool(schedule.get("enabled", True)),
            "interval_seconds": interval,
            "event": event_name,
            "source": source,
            "severity": severity,
        }

    def normalize_action(self, action):
        action_type = str(action.get("type") or "").strip()
        if action_type not in self.ACTION_TYPES:
            raise ValueError("unsupported automation action: %s" % (action_type or "missing"))
        clean = dict(action)
        clean["type"] = action_type
        if action_type == "webhook":
            url = str(clean.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("webhook action requires an http(s) url")
            clean["url"] = url
            clean["max_retries"] = max(1, min(3, int(clean.get("max_retries") or 1)))
            clean["timeout_seconds"] = max(1, min(30, int(clean.get("timeout_seconds") or 5)))
        return clean

    def redact(self, value):
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(part in lowered for part in self.SENSITIVE_PARTS):
                    clean[key] = "[redacted]"
                else:
                    clean[key] = self.redact(item)
            return clean
        if isinstance(value, list):
            return [self.redact(item) for item in value[:100]]
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "...[truncated]"
        return value

    def get_field(self, data, path):
        current = data
        for part in str(path or "").split("."):
            if not part:
                continue
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def severity_at_least(self, event, min_severity):
        if not min_severity:
            return True
        current = str(event.get("severity") or "medium").lower()
        return self.SEVERITY_WEIGHT.get(current, 2) >= self.SEVERITY_WEIGHT.get(min_severity, 2)

    def matches(self, rule, event):
        trigger = rule.get("trigger") or {}
        event_name = str(event.get("event") or event.get("type") or "")
        wanted_event = str(trigger.get("event") or "*")
        if wanted_event != "*" and event_name != wanted_event:
            return False
        wanted_source = str(trigger.get("source") or "")
        if wanted_source and str(event.get("source") or "") != wanted_source:
            return False
        if not self.severity_at_least(event, trigger.get("min_severity")):
            return False
        for key, wanted in (trigger.get("field_equals") or {}).items():
            if str(self.get_field(event, key)) != str(wanted):
                return False
        return True

    def sign_webhook(self, secret, timestamp, body):
        digest = hmac.new(str(secret or "").encode("utf-8"), ("%s.%s" % (timestamp, body)).encode("utf-8"), hashlib.sha256).hexdigest()
        return "sha256=" + digest

    def default_http_post(self, url, body, headers, timeout):
        req = Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return int(resp.status), text
        except HTTPError as exc:
            return int(exc.code), exc.read().decode("utf-8", errors="replace")
        except URLError as exc:
            return 599, str(exc.reason)

    def execute_webhook(self, action, event, execution_id):
        payload = {"execution_id": execution_id, "event": self.redact(event), "rule_action": {"type": "webhook", "url": action.get("url")}}
        body = json.dumps(payload, sort_keys=True)
        timestamp = str(int(self.clock()))
        headers = {
            "content-type": "application/json",
            "x-matts-event": str(event.get("event") or event.get("type") or ""),
            "x-matts-timestamp": timestamp,
            "x-matts-signature": self.sign_webhook(action.get("secret") or "", timestamp, body),
        }
        attempts = []
        for attempt in range(1, int(action.get("max_retries") or 1) + 1):
            status, response = self.http_post(action.get("url"), body, headers, int(action.get("timeout_seconds") or 5))
            attempts.append({"attempt": attempt, "status": int(status), "ok": int(status) < 400, "response": str(response or "")[:300]})
            if int(status) < 400:
                break
        return {"type": "webhook", "url": action.get("url"), "attempts": attempts, "ok": bool(attempts and attempts[-1]["ok"])}

    def execute_action(self, action, event, actor, execution_id, dry_run=False):
        action_type = action.get("type")
        if dry_run:
            return {"type": action_type, "planned": True, "action": self.redact(action)}
        if action_type == "create_review":
            payload = {
                "title": action.get("title") or "Automation review: %s" % (event.get("event") or event.get("type") or "event"),
                "reason": action.get("reason") or "automation_rule",
                "severity": action.get("severity") or event.get("severity") or "medium",
                "source": {"type": "automation", "event": event.get("event") or event.get("type"), "rule_source": event.get("source")},
                "evidence": self.redact(event),
                "actor": actor,
            }
            return {"type": action_type, "ok": True, "result": self.create_review_item(payload)}
        if action_type == "audit_event":
            name = str(action.get("action") or "automation.event")
            self.append_audit(name, actor=actor, outcome="completed", permission="automation.run", request={"event": self.redact(event)}, status=200)
            return {"type": action_type, "ok": True, "action": name}
        if action_type == "session_snapshot":
            field = action.get("session_field") or "session"
            session = self.get_field(event, field) or event.get("session_id") or event.get("session")
            if not session:
                return {"type": action_type, "ok": False, "error": "event has no session"}
            return {"type": action_type, "ok": True, "result": self.create_session_snapshot({"session": session, "actor": actor})}
        if action_type == "dedicated_event":
            state = str(action.get("state") or event.get("event") or "automation")
            message = str(action.get("message") or event.get("message") or "Automation rule matched.")
            severity = str(action.get("severity") or event.get("severity") or "info")
            self.append_dedicated_event(state, message, severity, {"automation_event": self.redact(event)})
            return {"type": action_type, "ok": True, "state": state}
        if action_type == "webhook":
            return self.execute_webhook(action, event, execution_id)
        if action_type == "run_eval":
            payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            payload = dict(payload)
            for key in ("dataset_id", "models", "baseline_run_id"):
                if key in action and key not in payload:
                    payload[key] = action.get(key)
            payload["trigger"] = {"type": "automation", "execution_id": execution_id, "event": event.get("event") or event.get("type"), "source": event.get("source")}
            return {"type": action_type, "ok": True, "result": self.run_eval(payload)}
        return {"type": action_type, "ok": False, "error": "unsupported action"}

    def append_execution(self, record):
        with self.log_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.redact(record), sort_keys=True) + "\n")

    def read_executions(self, limit=80):
        path = self.log_path()
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines()[-int(limit or 80):]:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def run_event(self, request, actor=None, dry_run=False):
        request = request if isinstance(request, dict) else {}
        event = request.get("event") if isinstance(request.get("event"), dict) else request
        actor = actor if isinstance(actor, dict) else event.get("actor") if isinstance(event.get("actor"), dict) else {}
        dry_run = bool(dry_run or request.get("dry_run"))
        config = self.load_config()
        execution_id = "automation_%d_%s" % (int(self.clock()), self.uuid_factory().hex[:8])
        matched = []
        for rule in config.get("rules") or []:
            if not rule.get("enabled") or not self.matches(rule, event):
                continue
            actions = [self.execute_action(action, event, actor, execution_id, dry_run=dry_run) for action in (rule.get("actions") or [])]
            matched.append({"rule": self.redact(rule), "actions": actions})
        record = {
            "id": execution_id,
            "created_at": float(self.clock()),
            "dry_run": dry_run,
            "event": self.redact(event),
            "matched_rules": matched,
            "matched_count": len(matched),
        }
        self.append_execution(record)
        self.append_audit("automation.test" if dry_run else "automation.run", actor=actor, outcome="completed", permission="automation_admin", request={"execution_id": execution_id, "matched_count": len(matched), "dry_run": dry_run}, status=200)
        return record

    def last_scheduled_runs(self):
        last = {}
        for execution in self.read_executions(limit=500):
            if execution.get("dry_run"):
                continue
            event = execution.get("event") if isinstance(execution.get("event"), dict) else {}
            if "scheduled_at" not in event:
                continue
            created_at = float(execution.get("created_at") or 0)
            for match in execution.get("matched_rules") or []:
                rule = match.get("rule") if isinstance(match, dict) and isinstance(match.get("rule"), dict) else {}
                rule_id = rule.get("id")
                if rule_id:
                    last[str(rule_id)] = max(float(last.get(str(rule_id)) or 0), created_at)
        return last

    def run_due_schedules(self, request=None, actor=None, dry_run=False):
        request = request if isinstance(request, dict) else {}
        actor = actor if isinstance(actor, dict) else request.get("actor") if isinstance(request.get("actor"), dict) else {}
        dry_run = bool(dry_run or request.get("dry_run"))
        now = float(self.clock())
        last_runs = self.last_scheduled_runs()
        schedules = []
        executed = []
        for rule in self.load_config().get("rules") or []:
            trigger = rule.get("trigger") if isinstance(rule.get("trigger"), dict) else {}
            schedule = trigger.get("schedule") if isinstance(trigger.get("schedule"), dict) else {}
            if not rule.get("enabled") or not schedule.get("enabled"):
                continue
            interval = int(schedule.get("interval_seconds") or 0)
            last_run_at = float(last_runs.get(rule.get("id")) or 0)
            next_run_at = last_run_at + interval if last_run_at else now
            due = not last_run_at or now >= next_run_at
            event = {
                "event": schedule.get("event") or "automation.schedule",
                "source": schedule.get("source") or "schedule",
                "severity": schedule.get("severity") or "medium",
                "rule_id": rule.get("id"),
                "scheduled_at": now,
            }
            row = {
                "rule_id": rule.get("id"),
                "name": rule.get("name"),
                "event": event,
                "due": due,
                "last_run_at": last_run_at or None,
                "next_run_at": next_run_at,
                "interval_seconds": interval,
            }
            if due and not dry_run:
                row["execution"] = self.run_event({"event": event}, actor=actor, dry_run=False)
                executed.append(row["execution"])
            schedules.append(row)
        self.append_audit("automation.schedules.test" if dry_run else "automation.schedules.run", actor=actor, outcome="completed", permission="automation_admin", request={"dry_run": dry_run, "due_count": len([row for row in schedules if row["due"]]), "executed_count": len(executed)}, status=200)
        return {"generated_at": now, "dry_run": dry_run, "schedules": schedules, "executed_count": len(executed)}

    def payload(self):
        return {"config": self.redact(self.load_config()), "executions": self.read_executions(limit=80), "actions": sorted(self.ACTION_TYPES)}
