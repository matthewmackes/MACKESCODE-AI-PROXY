"""AgentBoard tmux and usage aggregation helpers."""
import datetime
import hashlib
import time


class AgentBoardService:
    """Builds AgentBoard session, usage, and leaderboard payloads."""

    def __init__(self, ansi_re, permission_re, cache, tmux_cmd, local_usage_report, tail_jsonl, log_file, clock=None):
        self.ansi_re = ansi_re
        self.permission_re = permission_re
        self.cache = cache
        self.tmux_cmd = tmux_cmd
        self.local_usage_report = local_usage_report
        self.tail_jsonl = tail_jsonl
        self.log_file = log_file
        self.clock = clock or time.time

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

    def payload(self):
        sessions, error = self.sessions()
        usage, logs, status_counts = self.usage()
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
            "tasks": [{"session": s.get("name"), "status": s.get("status"), "path": s.get("path"), "last_prompt": s.get("last_prompt"), "panes": len(s.get("panes") or [])} for s in sessions],
            "evals": {"source": "local proxy logs and tmux status", "requests_ok": status_counts["ok"], "requests_error": status_counts["error"], "active_sessions": len(sessions), "spend_usd": usage.get("total_usd", 0)},
            "leaderboard": leaderboard[:20],
            "usage": usage,
            "logs": logs,
        }
