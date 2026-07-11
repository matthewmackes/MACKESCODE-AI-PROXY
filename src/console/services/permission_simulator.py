"""Claude Code permission preview helpers."""
from pathlib import Path


class PermissionSimulatorService:
    """Classify effective Claude Code launch permissions before tmux start."""

    modes = {
        "manual": {"level": "low", "allows_edits": False, "allows_bash": False},
        "plan": {"level": "low", "allows_edits": False, "allows_bash": False},
        "acceptEdits": {"level": "medium", "allows_edits": True, "allows_bash": False},
        "auto": {"level": "high", "allows_edits": True, "allows_bash": True},
        "dontAsk": {"level": "high", "allows_edits": True, "allows_bash": True},
        "bypassPermissions": {"level": "critical", "allows_edits": True, "allows_bash": True},
    }
    edit_tools = {"edit", "write", "multiedit", "notebookedit"}
    read_tools = {"read", "grep", "glob", "ls"}
    network_tools = {"webfetch", "websearch"}
    risky_bash_patterns = ("bash(*)", "bash", "bash(sudo", "bash(rm", "bash(chmod", "bash(chown", "bash(curl", "bash(wget")

    def __init__(self, project_dir):
        self.project_dir = project_dir

    def split_tools(self, value):
        raw = str(value or "").replace(",", " ").split()
        return [item.strip() for item in raw if item.strip()]

    def tool_name(self, value):
        return str(value or "").split("(", 1)[0].strip().lower()

    def split_dirs(self, value):
        return [line.strip() for line in str(value or "").splitlines() if line.strip()]

    def path_summary(self, project_dir, add_dirs):
        default_project = self.project_dir() if callable(self.project_dir) else self.project_dir
        base = Path(project_dir or default_project).expanduser()
        try:
            base_resolved = base.resolve()
        except OSError:
            base_resolved = base.absolute()
        rows = [{"path": str(base), "kind": "project", "inside_project": True, "exists": base.exists(), "risk": "normal"}]
        home = Path.home().resolve()
        for item in add_dirs:
            path = Path(item).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            try:
                inside = resolved == base_resolved or base_resolved in resolved.parents
            except RuntimeError:
                inside = False
            risk = "normal" if inside else "expanded_scope"
            if resolved == Path("/"):
                risk = "root_scope"
            elif resolved == home:
                risk = "home_scope"
            rows.append({"path": item, "kind": "add_dir", "inside_project": inside, "exists": path.exists(), "risk": risk})
        return rows

    def safer_preset(self, data, risk_level):
        profile = str(data.get("profile") or "").lower()
        run_mode = str(data.get("run_mode") or "interactive")
        if profile == "review" or run_mode in {"continue", "resume"}:
            return {"profile": "review", "permission_mode": "manual", "allowed_tools": "Read Grep Glob LS Bash(git status) Bash(git diff)", "disallowed_tools": "Edit Write MultiEdit Bash(rm *) Bash(sudo *)"}
        if risk_level in {"critical", "high"} or run_mode == "background":
            return {"profile": "careful", "permission_mode": "plan", "allowed_tools": "Read Grep Glob LS Bash(git status) Bash(git diff)", "disallowed_tools": "Edit Write MultiEdit Bash(rm *) Bash(sudo *)"}
        return {"profile": "builder", "permission_mode": "acceptEdits", "allowed_tools": "Read Grep Glob LS Edit Write", "disallowed_tools": "Bash(rm -rf *) Bash(shutdown *) Bash(reboot *)"}

    def simulate(self, data):
        data = data if isinstance(data, dict) else {}
        mode = str(data.get("permission_mode") or "acceptEdits")
        mode_info = self.modes.get(mode, {"level": "unknown", "allows_edits": False, "allows_bash": False})
        allowed = self.split_tools(data.get("allowed_tools"))
        denied = self.split_tools(data.get("disallowed_tools"))
        allowed_names = {self.tool_name(tool) for tool in allowed}
        denied_names = {self.tool_name(tool) for tool in denied}
        known = self.edit_tools | self.read_tools | self.network_tools | {"bash", "task", "todowrite"}
        unknown = [tool for tool in allowed + denied if self.tool_name(tool) not in known]
        paths = self.path_summary(data.get("project_dir"), self.split_dirs(data.get("add_dirs")))
        warnings = []

        def warn(code, severity, message):
            warnings.append({"code": code, "severity": severity, "message": message})

        if mode == "bypassPermissions":
            warn("permission_bypass", "critical", "bypassPermissions can approve tool use without normal prompts.")
        if mode in {"dontAsk", "auto"}:
            warn("autonomous_permission_mode", "high", "%s can reduce interactive review before tools run." % mode)
        if any(str(tool).lower().startswith("bash(*)") or str(tool).lower() == "bash" for tool in allowed):
            warn("broad_bash", "high", "Broad Bash access can execute arbitrary shell commands.")
        if allowed_names & self.edit_tools and not denied:
            warn("edits_without_denylist", "medium", "Edit-capable tools are allowed without a deny list.")
        if "bash" in allowed_names and not any("rm" in tool.lower() or "sudo" in tool.lower() for tool in denied):
            warn("bash_without_destructive_denies", "medium", "Bash is allowed without common destructive command denies.")
        for item in paths:
            if item["risk"] == "root_scope":
                warn("root_directory_scope", "critical", "A context directory points at filesystem root.")
            elif item["risk"] == "home_scope":
                warn("home_directory_scope", "high", "A context directory points at the operator home directory.")
            elif item["risk"] == "expanded_scope":
                warn("outside_project_scope", "medium", "A context directory is outside the selected project.")
        if data.get("extra_args") and "--dangerously" in str(data.get("extra_args")):
            warn("dangerous_extra_args", "critical", "Extra args include a dangerous option.")

        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        risk_level = mode_info["level"]
        for item in warnings:
            if severity_order.get(item["severity"], 0) > severity_order.get(risk_level, 0):
                risk_level = item["severity"]

        categories = {
            "allowed": allowed,
            "denied": denied,
            "risky": [tool for tool in allowed if any(str(tool).lower().startswith(pattern) for pattern in self.risky_bash_patterns)],
            "unknown": unknown,
        }
        return {
            "mode": mode,
            "risk_level": risk_level,
            "allows_edits": bool(mode_info.get("allows_edits") or (allowed_names & self.edit_tools)),
            "allows_bash": bool(mode_info.get("allows_bash") or "bash" in allowed_names),
            "categories": categories,
            "paths": paths,
            "warnings": warnings,
            "suggested_preset": self.safer_preset(data, risk_level),
            "override_allowed": True,
        }
