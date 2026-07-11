"""tmux-backed Claude Code launch and control helpers."""
import os
import shlex
import time
from http import HTTPStatus
from pathlib import Path


class TmuxControlService:
    """Owns launcher health, Claude args, tmux start, capture, input, and stop."""

    allowed_keys = {
        "Enter", "Escape", "Up", "Down", "Left", "Right", "Tab", "BTab",
        "C-c", "C-d", "C-u", "C-l", "PageUp", "PageDown", "Home", "End",
    }

    # Every console-managed tmux session name lives under this prefix. It is the
    # single security boundary that keeps the browser-exposed console from
    # attaching, capturing, writing, or killing arbitrary host tmux sessions
    # (e.g. `default` or another user's SSH session). See GOVERNANCE.md: tmux
    # terminal writes/reads are a security surface and the console binds 0.0.0.0.
    managed_prefix = "matts-"

    def __init__(
        self,
        script_dir,
        text_models,
        default_text_model,
        tmux_cmd,
        tmux_exists,
        tmux_target,
        tmux_capture_target,
        unique_tmux_session_name,
        tmux_session_name,
        tmux_registry_upsert,
        tmux_session_items,
        live_session_names,
        clock=None,
        sleep=None,
        geteuid=None,
    ):
        self.script_dir = script_dir
        self.text_models = text_models
        self.default_text_model = default_text_model
        self.tmux_cmd = tmux_cmd
        self.tmux_exists = tmux_exists
        self.tmux_target = tmux_target
        self.tmux_capture_target = tmux_capture_target
        self.unique_tmux_session_name = unique_tmux_session_name
        self.tmux_session_name = tmux_session_name
        self.tmux_registry_upsert = tmux_registry_upsert
        self.tmux_session_items = tmux_session_items
        self.live_session_names = live_session_names
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self.geteuid = geteuid or (os.geteuid if hasattr(os, "geteuid") else None)

    def active_text_models(self):
        return list(self.text_models() if callable(self.text_models) else self.text_models)

    def _ensure_managed(self, session):
        """Force a bare session name into the console-managed namespace.

        Idempotent: names that already carry the managed prefix are returned
        unchanged; empty input falls back to the managed default. Non-managed
        names (e.g. ``default``) are namespaced under the prefix so they can
        never resolve to a foreign host session.
        """
        session = str(session or "").strip()
        if not session:
            return self.managed_prefix + "claude"
        if not session.startswith(self.managed_prefix):
            session = self.managed_prefix + session
        return session

    def scoped_target(self, value):
        """Normalize and constrain a tmux target to the managed namespace.

        This is the single choke-point for every capture/send/attach/stop
        operation. It first runs the injected ``tmux_target`` sanitizer (strips
        unsafe characters, applies the managed default) and then guarantees the
        session component of the target carries the managed prefix. Pane targets
        of the form ``session:window.pane`` keep their window/pane suffix while
        only the session component is scoped.
        """
        target = self.tmux_target(value)
        session, sep, rest = str(target).partition(":")
        return self._ensure_managed(session) + sep + rest

    def launcher_health(self):
        launcher = self.script_dir() / "claude-DO.sh"
        backup = self.script_dir() / "claude-DO.sh.backup"
        required = ("start_proxy()", "exec claude")

        def valid(text):
            return all(item in text for item in required)

        try:
            text = launcher.read_text()
        except OSError as exc:
            text = ""
            read_error = str(exc)
        else:
            read_error = ""
        if valid(text):
            return {"ok": True, "healed": False, "path": str(launcher)}
        try:
            backup_text = backup.read_text()
        except OSError as exc:
            return {"ok": False, "healed": False, "path": str(launcher), "error": read_error or str(exc)}
        if not valid(backup_text):
            return {"ok": False, "healed": False, "path": str(launcher), "error": "launcher and backup are incomplete"}
        try:
            launcher.write_text(backup_text)
            launcher.chmod(0o755)
        except OSError as exc:
            return {"ok": False, "healed": False, "path": str(launcher), "error": str(exc)}
        return {"ok": True, "healed": True, "path": str(launcher)}

    def screen(self, name, lines="-80"):
        code, out, err = self.tmux_cmd(["capture-pane", "-p", "-e", "-J", "-S", lines, "-t", name], check=False)
        return code, out, err

    def has_completed_claude(self, name):
        code, out, _ = self.screen(name)
        if code != 0:
            return False, ""
        markers = ("[Claude Code exited with status", "Session remains open for inspection")
        return all(marker in out for marker in markers), out

    def split_lines(self, value):
        return [line.strip() for line in str(value or "").splitlines() if line.strip()]

    def claude_launch_args(self, data):
        args = []
        permission_mode = data.get("permission_mode")
        if permission_mode == "bypassPermissions" and self.geteuid and self.geteuid() == 0:
            permission_mode = "acceptEdits"
        if permission_mode in {"acceptEdits", "bypassPermissions", "plan", "manual", "dontAsk", "auto"}:
            args += ["--permission-mode", permission_mode]
        setting_sources = data.get("setting_sources")
        if setting_sources:
            args += ["--setting-sources", str(setting_sources)]
        if data.get("safe_mode"):
            args.append("--safe-mode")
        if data.get("bare"):
            args.append("--bare")
        for directory in self.split_lines(data.get("add_dirs")):
            args += ["--add-dir", directory]
        allowed = str(data.get("allowed_tools") or "").strip()
        if allowed:
            args += ["--allowedTools", allowed]
        disallowed = str(data.get("disallowed_tools") or "").strip()
        if disallowed:
            args += ["--disallowedTools", disallowed]
        session_name = str(data.get("claude_session_name") or "").strip()
        if session_name:
            args += ["--name", session_name]
        run_mode = data.get("run_mode") or "interactive"
        prompt = str(data.get("print_prompt") or "").strip()
        budget = str(data.get("max_budget_usd") or "").strip()
        if run_mode in {"print", "json", "stream-json"}:
            args.append("--print")
            if budget:
                args += ["--max-budget-usd", budget]
            if run_mode == "json":
                args += ["--output-format", "json"]
            elif run_mode == "stream-json":
                args += ["--output-format", "stream-json"]
            else:
                output_format = data.get("output_format")
                if output_format in {"text", "json", "stream-json"}:
                    args += ["--output-format", output_format]
            if data.get("no_session_persistence"):
                args.append("--no-session-persistence")
            if prompt:
                args.append(prompt)
        elif run_mode == "background":
            args.append("--bg")
            if prompt:
                args.append(prompt)
        elif run_mode == "continue":
            args.append("--continue")
        elif run_mode == "resume":
            resume_value = str(data.get("resume") or "").strip()
            args.append("--resume")
            if resume_value:
                args.append(resume_value)
        args += shlex.split(str(data.get("extra_args") or ""))
        return args

    def color_env_exports(self):
        return "unset NO_COLOR; export COLORTERM=truecolor FORCE_COLOR=3 CLICOLOR=1 CLICOLOR_FORCE=1; "

    def start(self, data):
        health = self.launcher_health()
        if not health.get("ok"):
            return HTTPStatus.BAD_REQUEST, {"error": "Claude launcher is not runnable", "launcher": health}
        model = data.get("model") if data.get("model") in self.active_text_models() else self.default_text_model()
        project_dir = data.get("project_dir") or str(self.script_dir())
        if not Path(project_dir).is_dir():
            return HTTPStatus.BAD_REQUEST, {"error": "project directory does not exist"}
        display_name = str(data.get("display_name") or data.get("name") or "matts-claude").strip() or "matts-claude"
        # Scope the requested name to the managed namespace before resolving it,
        # otherwise start() itself becomes an attach vector for a foreign session
        # (existing-session branch returns a captured screen with attached=True).
        requested_name = self._ensure_managed(data.get("name") or display_name)
        name = self.unique_tmux_session_name(requested_name) if data.get("new_session") else self.tmux_session_name(requested_name)
        run_mode = data.get("run_mode") or "interactive"
        reset_dead_session = False
        if self.tmux_exists(name):
            completed, screen = self.has_completed_claude(name)
            if completed and run_mode == "interactive":
                self.stop(name)
                reset_dead_session = True
            else:
                payload_data = dict(data)
                payload_data["display_name"] = display_name
                self.tmux_registry_upsert(name, data=payload_data, live=True)
                return HTTPStatus.OK, {"name": name, "attached": True, "launcher": health, "sessions": self.tmux_session_items()}
        command = [str(self.script_dir() / "claude-DO.sh"), "--model", model] + self.claude_launch_args(data)
        shell_command = (
            "printf 'Starting Claude Code session: %s\\n'; "
            "%s"
            "%s; "
            "code=$?; "
            "printf '\\n[Claude Code exited with status %%s]\\n' \"$code\"; "
            "printf 'Session remains open for inspection. Press Ctrl-D or kill the session from the console.\\n'; "
            "exec ${SHELL:-/bin/bash}"
        ) % (shlex.quote(name), self.color_env_exports(), shlex.join(command))
        code, _, err = self.tmux_cmd([
            "new-session",
            "-d",
            "-s",
            name,
            "-e",
            "COLORTERM=truecolor",
            "-e",
            "FORCE_COLOR=3",
            "-e",
            "CLICOLOR=1",
            "-e",
            "CLICOLOR_FORCE=1",
            "-x",
            str(int(data.get("cols") or 120)),
            "-y",
            str(int(data.get("rows") or 40)),
            "-c",
            project_dir,
            shell_command,
        ], check=False)
        if code != 0:
            return HTTPStatus.BAD_REQUEST, {"error": err or "tmux failed to start"}
        for _ in range(10):
            if self.tmux_exists(name):
                if run_mode == "interactive":
                    self.sleep(0.3)
                    completed, screen = self.has_completed_claude(name)
                    if completed:
                        self.stop(name)
                        return HTTPStatus.BAD_REQUEST, {
                            "error": "Claude exited immediately after tmux start",
                            "name": name,
                            "launcher": health,
                            "screen": screen[-4000:],
                        }
                payload_data = dict(data)
                payload_data["display_name"] = display_name
                self.tmux_registry_upsert(name, data=payload_data, live=True)
                return HTTPStatus.OK, {"name": name, "display_name": display_name, "attached": False, "launcher": health, "reset": reset_dead_session, "sessions": self.tmux_session_items()}
            self.sleep(0.1)
        code, out, err = self.tmux_cmd(["list-sessions", "-F", "#{session_name}"], check=False)
        return HTTPStatus.BAD_REQUEST, {"error": "tmux session did not become addressable", "name": name, "sessions": out.splitlines(), "detail": err}

    def capture(self, name):
        name = self.scoped_target(name)
        code, out, err = self.tmux_capture_target(name, "-200")
        if code != 0:
            return HTTPStatus.NOT_FOUND, {"error": err or "tmux session not found", "name": name}
        return HTTPStatus.OK, {"name": name, "screen": out}

    def send_text(self, name, text, enter=False):
        name = self.scoped_target(name)
        buffer_name = name + "-paste"
        code, _, err = self.tmux_cmd(["set-buffer", "-b", buffer_name, text or ""], check=False)
        if code != 0:
            return HTTPStatus.BAD_REQUEST, {"error": err or "tmux set-buffer failed"}
        code, _, err = self.tmux_cmd(["paste-buffer", "-t", name, "-b", buffer_name], check=False)
        if code != 0:
            return HTTPStatus.BAD_REQUEST, {"error": err or "tmux paste failed"}
        if enter:
            self.tmux_cmd(["send-keys", "-t", name, "Enter"], check=False)
        return HTTPStatus.OK, {"ok": True}

    def send_key(self, name, key):
        name = self.scoped_target(name)
        if key not in self.allowed_keys:
            return HTTPStatus.BAD_REQUEST, {"error": "key is not allowed"}
        code, _, err = self.tmux_cmd(["send-keys", "-t", name, key], check=False)
        if code != 0:
            return HTTPStatus.BAD_REQUEST, {"error": err or "tmux send-keys failed"}
        return HTTPStatus.OK, {"ok": True}

    def stop(self, name):
        name = self.scoped_target(name)
        code, _, err = self.tmux_cmd(["kill-session", "-t", name], check=False)
        if code not in (0, 1):
            return HTTPStatus.BAD_REQUEST, {"error": err or "tmux kill-session failed"}
        self.tmux_registry_upsert(name, live=False, stopped=True)
        return HTTPStatus.OK, {"ok": True}

    def sessions(self):
        return self.live_session_names()
