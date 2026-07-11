"""AgentBoard tmux, usage, and execution graph aggregation helpers."""
import datetime
import hashlib
import time


class AgentBoardService:
    """Builds AgentBoard session, usage, and leaderboard payloads."""

    # AgentBoard captures pane previews. Only console-managed sessions may be
    # surfaced; foreign host tmux sessions must not leak through this payload.
    managed_prefix = "matts-"

    def __init__(
        self,
        ansi_re,
        permission_re,
        cache,
        tmux_cmd,
        local_usage_report,
        tail_jsonl,
        log_file,
        clock=None,
        read_traces=None,
        audit_file=None,
        resource_monitor=None,
    ):
        self.ansi_re = ansi_re
        self.permission_re = permission_re
        self.cache = cache
        self.tmux_cmd = tmux_cmd
        self.local_usage_report = local_usage_report
        self.tail_jsonl = tail_jsonl
        self.log_file = log_file
        self.clock = clock or time.time
        self.read_traces = read_traces
        self.audit_file = audit_file
        self.resource_monitor = resource_monitor

    def strip_ansi(self, value):
        return self.ansi_re.sub("", str(value or ""))

    def tmux_target(self, value, default="matts-claude"):
        raw = str(value or default).strip()
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_:.")
        return cleaned[:140] if cleaned else default

    def tmux_capture_target(self, target, lines="-200"):
        target = self.tmux_target(target)
        code, out, err = self.tmux_cmd(["capture-pane", "-p", "-e", "-J", "-S", str(lines), "-t", target], check=False)
        if code != 0:
            return code, "", err or "tmux capture failed"
        return code, out, ""

    def infer_status(self, target, screen, width=0, height=0):
        now = self.clock()
        clean = self.strip_ansi(screen)
        recent = "\n".join([line for line in clean.splitlines() if line.strip()][-10:])
        digest = hashlib.sha1((clean + "|%s|%s" % (width, height)).encode("utf-8", errors="replace")).hexdigest()
        previous = self.cache.get(target)
        changed = bool(previous and previous.get("digest") != digest)
        last_changed = now if changed or not previous else float(previous.get("last_changed") or now)
        self.cache[target] = {"digest": digest, "last_changed": last_changed}
        if changed:
            status = "working"
        elif self.permission_re.search(recent):
            status = "permission"
        elif previous and now - last_changed < 10:
            status = "working"
        else:
            status = "waiting"
        return status, last_changed

    def last_prompt_from_screen(self, screen):
        clean = self.strip_ansi(screen)
        candidates = []
        for line in clean.splitlines():
            text = line.strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered.startswith((">", "user:", "human:")) or "prompt" in lowered or "task" in lowered:
                candidates.append(text)
        if not candidates:
            candidates = [line.strip() for line in clean.splitlines() if line.strip()]
        return (candidates[-1] if candidates else "")[:240]

    def sessions(self):
        fmt = "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_width}\t#{pane_height}\t#{pane_pid}\t#{pane_active}"
        code, out, err = self.tmux_cmd(["list-panes", "-a", "-F", fmt], check=False)
        if code != 0:
            return [], err or "tmux is unavailable"
        sessions = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 10:
                continue
            session, window_index, window_name, pane_index, command, path, width, height, pid, active = parts[:10]
            # Scope to console-managed sessions only: skip foreign panes before
            # capturing their screen so their contents never enter the payload.
            if not str(session).startswith(self.managed_prefix):
                continue
            target = "%s:%s.%s" % (session, window_index, pane_index)
            _, screen, _ = self.tmux_capture_target(target, "-120")
            try:
                width_i = int(width or 0)
                height_i = int(height or 0)
            except ValueError:
                width_i = height_i = 0
            status, last_changed = self.infer_status(target, screen, width_i, height_i)
            item = sessions.setdefault(session, {
                "name": session,
                "target": session,
                "status": status,
                "panes": [],
                "path": path,
                "last_changed": last_changed,
                "last_prompt": "",
                "active": False,
            })
            item["panes"].append({
                "target": target,
                "window": window_name,
                "window_index": window_index,
                "pane_index": pane_index,
                "command": command,
                "path": path,
                "pid": pid,
                "active": active == "1",
                "width": width_i,
                "height": height_i,
                "status": status,
                "preview": self.strip_ansi(screen)[-1200:],
            })
            if active == "1" or not item.get("last_prompt"):
                item["status"] = status
                item["path"] = path
                item["last_changed"] = last_changed
                item["last_prompt"] = self.last_prompt_from_screen(screen)
                item["active"] = item["active"] or active == "1"
        order = {"permission": 0, "working": 1, "waiting": 2}
        rows = list(sessions.values())
        if callable(self.resource_monitor):
            monitor = self.resource_monitor()
            for item in rows:
                resources = monitor.summarize(item.get("name"), project_dir=item.get("path"), panes=item.get("panes") or [])
                item["resource_metrics"] = resources
                item["resource_warnings"] = resources.get("warnings") or []
        rows.sort(key=lambda item: (order.get(item.get("status"), 9), item.get("name", "")))
        return rows, ""

    def usage(self):
        today = datetime.datetime.fromtimestamp(self.clock(), datetime.timezone.utc).date()
        usage = self.local_usage_report(today - datetime.timedelta(days=6), today)
        logs = self.tail_jsonl(self.log_file(), limit=200)
        status_counts = {"ok": 0, "error": 0}
        for row in logs:
            if not isinstance(row, dict):
                continue
            try:
                code = int(row.get("status") or row.get("status_code") or 0)
            except (TypeError, ValueError):
                code = 0
            if code >= 400 or row.get("error"):
                status_counts["error"] += 1
            elif code:
                status_counts["ok"] += 1
        return usage, logs[-25:], status_counts

    def event_id(self, session, source, seed):
        material = "%s|%s|%s" % (session, source, seed)
        return hashlib.sha1(material.encode("utf-8", errors="replace")).hexdigest()[:16]

    def redacted_summary(self, text, limit=180):
        clean = " ".join(self.strip_ansi(text).split())
        return clean[:limit]

    def event(self, session, event_type, title, ts=None, source="inferred", confidence="inferred", **extra):
        payload = {
            "id": self.event_id(session, source, "%s|%s|%s" % (event_type, title, ts or self.clock())),
            "session": session,
            "timestamp": ts,
            "event_type": event_type,
            "title": title,
            "source": source,
            "confidence": confidence,
            "evidence": extra.pop("evidence", {}),
        }
        payload.update({key: value for key, value in extra.items() if value not in (None, "", [])})
        return payload

    def trace_events(self, session):
        if not callable(self.read_traces):
            return []
        try:
            traces = self.read_traces(limit=500, session=session)
        except Exception:
            return []
        events = []
        for row in traces or []:
            if not isinstance(row, dict):
                continue
            trace_id = row.get("trace_id") or ""
            status = row.get("status") or "unknown"
            routed = row.get("routed_model") or row.get("requested_model") or ""
            summary = row.get("message_summary") if isinstance(row.get("message_summary"), dict) else {}
            title = "Model route %s" % routed if routed else "Model route"
            events.append(self.event(
                session,
                "model_route",
                title,
                ts=row.get("timestamp"),
                source="trace",
                confidence="direct",
                status=status,
                requested_model=row.get("requested_model"),
                routed_model=row.get("routed_model"),
                endpoint_mode=row.get("endpoint_mode"),
                routing_reason=row.get("routing_reason"),
                cost_usd=row.get("cost_usd"),
                latency_ms=row.get("latency_ms"),
                trace_id=trace_id,
                summary=self.redacted_summary(summary.get("last_user_preview") or row.get("human_message") or ""),
                evidence={"trace_id": trace_id},
            ))
            if status == "error" or row.get("error_category"):
                events.append(self.event(
                    session,
                    "error",
                    row.get("error_category") or "Model request error",
                    ts=row.get("timestamp"),
                    source="trace",
                    confidence="direct",
                    status=status,
                    trace_id=trace_id,
                    summary=self.redacted_summary(row.get("human_message") or ""),
                    evidence={"trace_id": trace_id},
                ))
        return events

    def audit_events(self, session):
        if not callable(self.audit_file):
            return []
        rows = self.tail_jsonl(self.audit_file(), limit=500)
        events = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            request = row.get("request") if isinstance(row.get("request"), dict) else {}
            body = request.get("body") if isinstance(request.get("body"), dict) else {}
            actor = row.get("actor") if isinstance(row.get("actor"), dict) else {}
            names = {body.get("name"), body.get("session_id"), request.get("session_id"), actor.get("id")}
            if session not in {str(item) for item in names if item}:
                continue
            action = row.get("action") or "operator action"
            events.append(self.event(
                session,
                "operator_action",
                action,
                ts=row.get("ts"),
                source="audit",
                confidence="direct",
                status=row.get("outcome"),
                permission=row.get("permission"),
                http_status=row.get("status"),
                summary=self.redacted_summary("%s %s" % (request.get("path") or "", body.get("text") or "")),
                evidence={"audit_action": action, "actor": actor.get("id")},
            ))
        return events

    def session_events(self, session):
        name = session.get("name") or "unknown"
        now = self.clock()
        events = [
            self.event(
                name,
                "session_state",
                "Session %s" % (session.get("status") or "unknown"),
                ts=session.get("last_changed") or now,
                source="session_registry",
                confidence="direct",
                status=session.get("status"),
                path=session.get("path"),
                evidence={"session": name},
            )
        ]
        last_prompt = session.get("last_prompt")
        if last_prompt:
            events.append(self.event(
                name,
                "prompt_inferred",
                "Latest prompt/task",
                ts=session.get("last_changed") or now,
                source="tmux_capture",
                confidence="inferred",
                summary=self.redacted_summary(last_prompt),
                evidence={"session": name},
            ))
        if session.get("status") == "permission":
            events.append(self.event(
                name,
                "approval_prompt",
                "Approval prompt detected",
                ts=now,
                source="tmux_capture",
                confidence="inferred",
                status="waiting",
                evidence={"session": name},
            ))
        for pane in session.get("panes") or []:
            target = pane.get("target") or name
            preview = pane.get("preview") or ""
            events.append(self.event(
                name,
                "process",
                pane.get("command") or "process",
                ts=session.get("last_changed") or now,
                source="tmux",
                confidence="direct",
                status=pane.get("status"),
                path=pane.get("path"),
                evidence={"target": target, "pid": pane.get("pid")},
            ))
            if preview:
                events.append(self.event(
                    name,
                    "terminal_snapshot",
                    "Terminal snapshot",
                    ts=now,
                    source="tmux_capture",
                    confidence="inferred",
                    summary=self.redacted_summary(preview),
                    preview_digest=hashlib.sha1(preview.encode("utf-8", errors="replace")).hexdigest()[:16],
                    evidence={"target": target},
                ))
        events.extend(self.trace_events(name))
        events.extend(self.audit_events(name))
        events.sort(key=lambda item: (float(item.get("timestamp") or 0), item.get("event_type") or "", item.get("id") or ""))
        return events

    def execution_graphs(self, sessions):
        graphs = []
        for session in sessions:
            name = session.get("name") or "unknown"
            events = self.session_events(session)
            edges = []
            for index in range(1, len(events)):
                edges.append({"from": events[index - 1]["id"], "to": events[index]["id"], "relation": "next"})
            total_cost = round(sum(float(item.get("cost_usd") or 0.0) for item in events), 8)
            graphs.append({
                "session": name,
                "status": session.get("status"),
                "nodes": events,
                "edges": edges,
                "summary": {
                    "event_count": len(events),
                    "direct_count": len([item for item in events if item.get("confidence") == "direct"]),
                    "inferred_count": len([item for item in events if item.get("confidence") == "inferred"]),
                    "total_cost_usd": total_cost,
                    "error_count": len([item for item in events if item.get("event_type") == "error" or item.get("status") in {"error", "failed", "denied"}]),
                },
                "privacy": "Timeline nodes use trace metadata, audit metadata, and short tmux summaries. Full prompts and terminal output are not stored in graph nodes.",
            })
        return graphs

    def payload(self):
        sessions, error = self.sessions()
        usage, logs, status_counts = self.usage()
        graphs = self.execution_graphs(sessions)
        graph_by_session = {graph["session"]: graph for graph in graphs}
        counts = {"working": 0, "waiting": 0, "permission": 0, "unknown": 0}
        for session in sessions:
            counts[session.get("status") if session.get("status") in counts else "unknown"] += 1
        leaderboard = []
        for row in usage.get("by_model") or []:
            leaderboard.append({"name": row.get("model"), "score": row.get("amount_usd"), "metric": "local spend usd"})
        if not leaderboard:
            for session in sessions:
                leaderboard.append({"name": session.get("name"), "score": len(session.get("panes") or []), "metric": "active panes"})
        return {
            "generated_at": self.clock(),
            "error": error,
            "sessions": sessions,
            "counts": counts,
            "tasks": [{"session": s.get("name"), "status": s.get("status"), "path": s.get("path"), "last_prompt": s.get("last_prompt"), "panes": len(s.get("panes") or []), "cpu_percent": (s.get("resource_metrics") or {}).get("cpu_percent"), "rss_mb": (s.get("resource_metrics") or {}).get("rss_mb"), "resource_warnings": s.get("resource_warnings") or [], "events": (graph_by_session.get(s.get("name")) or {}).get("summary", {}).get("event_count", 0)} for s in sessions],
            "graphs": graphs,
            "evals": {"source": "local proxy logs and tmux status", "requests_ok": status_counts["ok"], "requests_error": status_counts["error"], "active_sessions": len(sessions), "spend_usd": usage.get("total_usd", 0)},
            "leaderboard": leaderboard[:20],
            "usage": usage,
            "logs": logs,
        }
