"""Local tmux session resource monitoring."""
import os
import shutil
import subprocess
from pathlib import Path


class SessionResourceService:
    """Collect local process and disk metrics for tmux-backed sessions."""

    artifact_dirs = ("build", "dist", "frontend/dist", "images", ".cache")

    def __init__(self, tmux_cmd, clock=None, process_runner=None, disk_usage=None):
        self.tmux_cmd = tmux_cmd
        self.clock = clock
        self.process_runner = process_runner or self.default_process_runner
        self.disk_usage = disk_usage or shutil.disk_usage

    def default_process_runner(self):
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,pcpu=,rss=,etimes=,comm="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ps failed")
        return result.stdout

    def int_value(self, value, default=0):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default

    def float_value(self, value, default=0.0):
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return default

    def tmux_panes(self, session_name):
        fmt = "#{session_name}\t#{pane_pid}\t#{pane_current_path}\t#{pane_current_command}"
        code, out, err = self.tmux_cmd(["list-panes", "-a", "-F", fmt], check=False)
        if code != 0:
            return [], err or "tmux list-panes failed"
        panes = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 4 or parts[0] != session_name:
                continue
            panes.append({"pid": parts[1], "path": parts[2], "command": parts[3]})
        return panes, ""

    def process_table(self):
        rows = {}
        children = {}
        try:
            output = self.process_runner()
        except Exception as exc:
            return rows, children, str(exc)
        for line in str(output or "").splitlines():
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            pid = self.int_value(parts[0])
            ppid = self.int_value(parts[1])
            row = {
                "pid": pid,
                "ppid": ppid,
                "cpu_percent": self.float_value(parts[2]),
                "rss_mb": round(self.int_value(parts[3]) / 1024.0, 2),
                "age_seconds": self.int_value(parts[4]),
                "command": Path(parts[5]).name[:80],
            }
            rows[pid] = row
            children.setdefault(ppid, []).append(pid)
        return rows, children, ""

    def descendant_pids(self, roots, child_map):
        seen = set()
        stack = [pid for pid in roots if pid]
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            stack.extend(child_map.get(pid) or [])
        return seen

    def dir_size(self, root, max_files=2000):
        total = 0
        count = 0
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in {".git", "node_modules", "__pycache__"}]
            for name in files:
                try:
                    total += (Path(current) / name).stat().st_size
                except OSError:
                    continue
                count += 1
                if count >= max_files:
                    return total, True
        return total, False

    def disk_summary(self, project_dir):
        path = Path(project_dir or ".").expanduser()
        try:
            usage = self.disk_usage(path)
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        artifact_bytes = 0
        truncated = False
        for rel in self.artifact_dirs:
            target = path / rel
            if not target.exists():
                continue
            size, was_truncated = self.dir_size(target)
            artifact_bytes += size
            truncated = truncated or was_truncated
        total = max(1, int(usage.total))
        used = max(0, int(usage.used))
        return {
            "available": True,
            "path": str(path),
            "total_gb": round(total / (1024 ** 3), 2),
            "free_gb": round(int(usage.free) / (1024 ** 3), 2),
            "used_percent": round((used / total) * 100, 2),
            "artifact_mb": round(artifact_bytes / (1024 ** 2), 2),
            "artifact_scan_truncated": truncated,
        }

    def warnings(self, metrics, idle_seconds=0):
        warnings = []

        def add(code, severity, message):
            warnings.append({"code": code, "severity": severity, "message": message})

        if metrics.get("cpu_percent", 0) >= 250:
            add("runaway_cpu", "high", "Session process tree is using high CPU.")
        if metrics.get("rss_mb", 0) >= 2048:
            add("high_memory", "high", "Session process tree is using high memory.")
        if int(idle_seconds or 0) >= 4 * 3600:
            add("stale_session", "medium", "Session has been idle for more than four hours.")
        disk = metrics.get("disk") if isinstance(metrics.get("disk"), dict) else {}
        if disk.get("available") and disk.get("used_percent", 0) >= 90:
            add("low_disk_space", "high", "Workspace filesystem is above 90 percent used.")
        if disk.get("artifact_mb", 0) >= 512:
            add("large_artifacts", "medium", "Generated artifacts exceed 512 MB.")
        return warnings

    def summarize(self, session_name, project_dir="", idle_seconds=0, panes=None):
        errors = []
        panes = list(panes) if isinstance(panes, list) else None
        if panes is None:
            panes, err = self.tmux_panes(session_name)
            if err:
                errors.append(err)
        roots = [self.int_value(pane.get("pid")) for pane in panes or [] if isinstance(pane, dict)]
        process_rows, child_map, err = self.process_table()
        if err:
            errors.append(err)
        all_pids = self.descendant_pids(roots, child_map) if process_rows else set(roots)
        rows = [process_rows[pid] for pid in all_pids if pid in process_rows]
        commands = sorted({row["command"] for row in rows if row.get("command")})
        cpu = round(sum(row.get("cpu_percent", 0.0) for row in rows), 2)
        rss = round(sum(row.get("rss_mb", 0.0) for row in rows), 2)
        age = max([row.get("age_seconds", 0) for row in rows] or [0])
        disk = self.disk_summary(project_dir)
        if not disk.get("available"):
            errors.append(disk.get("error") or "disk usage unavailable")
        metrics = {
            "available": not bool(errors),
            "errors": errors,
            "pane_count": len(panes or []),
            "pane_pids": roots,
            "child_process_count": max(0, len(all_pids - set(roots))),
            "cpu_percent": cpu,
            "rss_mb": rss,
            "max_process_age_seconds": age,
            "commands": commands[:12],
            "disk": disk,
            "privacy": "Process command names are reported without command arguments.",
        }
        metrics["warnings"] = self.warnings(metrics, idle_seconds=idle_seconds)
        return metrics
