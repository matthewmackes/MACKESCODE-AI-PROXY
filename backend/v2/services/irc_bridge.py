"""Stdlib IRC bridge for remote LLM chat clients."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import shlex
import signal
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from backend.v2.services.chat_response import normalize_chat_result
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.model_showcase import ModelShowcaseService
from src.console.services.app_config import ConsoleConfigService
from src.console.services.runtime_config import RuntimeConfigService


PROJECT_DIR = Path(__file__).resolve().parents[3]
CONSOLE_ENTRYPOINT = PROJECT_DIR / "image-studio.py"
DEFAULT_CONSOLE_CONFIG = PROJECT_DIR / "config" / "console.json"
DEFAULT_SESSION_NAME = "matts-irc-bridge"
DEFAULT_CHANNEL = "#llms"
SERVER_NAME = "matts-irc"
IRC_LINE_LIMIT = 430


def _read_console_config() -> dict[str, Any]:
    path = Path(os.environ.get("MATTS_CONSOLE_CONFIG_FILE", DEFAULT_CONSOLE_CONFIG))
    try:
        return ConsoleConfigService(file_path=CONSOLE_ENTRYPOINT, config_path=path).load()
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        return data if isinstance(data, dict) else {}


def runtime_config() -> RuntimeConfigService:
    return RuntimeConfigService(file_path=CONSOLE_ENTRYPOINT, config=_read_console_config())


def owner_console_token() -> str:
    raw = os.environ.get("MATTS_CONSOLE_AUTH_TOKEN", "") or os.environ.get("MATTS_CONSOLE_TOKEN", "")
    if raw:
        return raw.strip()
    return runtime_config().auth_token()


def runtime_dir() -> Path:
    raw = os.environ.get("MATTS_RUNTIME_DIR", "").strip()
    if raw:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return runtime_config().app_dir()


def tmux_tmpdir() -> Path:
    raw = os.environ.get("TMUX_TMPDIR", "").strip()
    path = Path(raw) if raw else runtime_dir().parent / "tmux"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def int_range(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def clean_session_name(value: Any, default: str = DEFAULT_SESSION_NAME) -> str:
    raw = str(value or default).strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_:.")
    return cleaned[:120] if cleaned else default


def clean_host(value: Any) -> str:
    raw = str(value or "").strip()
    return raw or "0.0.0.0"


def load_json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def parse_irc_line(line: str) -> tuple[str, list[str]]:
    text = line.rstrip("\r\n")
    if text.startswith(":"):
        text = text.split(" ", 1)[1] if " " in text else ""
    trailing = None
    if " :" in text:
        text, trailing = text.split(" :", 1)
    parts = [part for part in text.split(" ") if part]
    if not parts:
        return "", []
    command = parts[0].upper()
    params = parts[1:]
    if trailing is not None:
        params.append(trailing)
    return command, params


def irc_nick(value: str, fallback: str) -> str:
    raw = str(value or fallback).strip()
    cleaned = re.sub(r"[^A-Za-z0-9_\-\[\]\\`^{}]", "_", raw)
    cleaned = cleaned.strip("_-") or fallback
    if not re.match(r"^[A-Za-z_\[\]\\`^{}]", cleaned):
        cleaned = "llm_" + cleaned
    return cleaned[:30]


def text_chunks(text: str, limit: int = IRC_LINE_LIMIT) -> list[str]:
    rows: list[str] = []
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line or " "
        while len(line.encode("utf-8", errors="replace")) > limit:
            chunk = line[:limit]
            while len(chunk.encode("utf-8", errors="replace")) > limit and len(chunk) > 1:
                chunk = chunk[:-1]
            rows.append(chunk)
            line = line[len(chunk):]
        rows.append(line)
    return rows or [" "]


class IrcBridgeConfigStore:
    """Load and validate the bridge runtime config."""

    def __init__(self, path: Path | None = None, metadata_path: Path | None = None) -> None:
        base = runtime_dir()
        self.path = path or Path(os.environ.get("MATTS_IRC_CONFIG_FILE", base / "irc-bridge.json"))
        self.metadata_path = metadata_path or Path(os.environ.get("MATTS_IRC_METADATA_LOG", base / "irc-bridge-metadata.jsonl"))

    def defaults(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "enabled": True,
            "host": "0.0.0.0",
            "port": 6667,
            "tls_enabled": False,
            "tls_cert_file": "",
            "tls_key_file": "",
            "session_name": DEFAULT_SESSION_NAME,
            "channel": DEFAULT_CHANNEL,
            "metadata_log": str(self.metadata_path),
            "restart_delay_seconds": 2,
        }

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = {**self.defaults(), **(payload or {})}
        data["enabled"] = bool_value(data.get("enabled"), True)
        data["host"] = clean_host(data.get("host"))
        data["port"] = int_range(data.get("port"), 6667, 1, 65535)
        data["tls_enabled"] = bool_value(data.get("tls_enabled"), False)
        data["tls_cert_file"] = str(data.get("tls_cert_file") or "").strip()
        data["tls_key_file"] = str(data.get("tls_key_file") or "").strip()
        data["session_name"] = clean_session_name(data.get("session_name"))
        channel = str(data.get("channel") or DEFAULT_CHANNEL).strip()
        data["channel"] = channel if channel.startswith("#") else DEFAULT_CHANNEL
        data["metadata_log"] = str(Path(str(data.get("metadata_log") or self.metadata_path)))
        data["restart_delay_seconds"] = int_range(data.get("restart_delay_seconds"), 2, 1, 60)
        return data

    def load(self) -> dict[str, Any]:
        return self.normalize(load_json_file(self.path, self.defaults()))

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        merged = {**current, **(payload or {})}
        normalized = self.normalize(merged)
        atomic_write_json(self.path, normalized)
        return normalized


class IrcModelDirectory:
    """Expose routable text models as IRC contact nicks."""

    def __init__(self, showcase_service: ModelShowcaseService | None = None) -> None:
        self.showcase_service = showcase_service or ModelShowcaseService()

    def models(self) -> list[dict[str, Any]]:
        payload = self.showcase_service.payload()
        rows = payload.get("models") if isinstance(payload, dict) else []
        models = [dict(model) for model in rows if isinstance(model, dict) and model.get("type") == "text" and model.get("route_enabled")]
        seen: set[str] = set()
        for model in models:
            base = irc_nick(str(model.get("display_name") or model.get("id") or "model"), "llm")
            nick = base
            suffix = 2
            while nick.lower() in seen:
                nick = f"{base[:26]}_{suffix}"
                suffix += 1
            seen.add(nick.lower())
            model["irc_nick"] = nick
        return models

    def maps(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        by_nick: dict[str, dict[str, Any]] = {}
        by_id: dict[str, dict[str, Any]] = {}
        for model in self.models():
            by_nick[str(model["irc_nick"]).lower()] = model
            by_id[str(model.get("id") or "").lower()] = model
        return by_nick, by_id


class IrcMetadataLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, payload: dict[str, Any]) -> None:
        row = dict(payload)
        row.setdefault("ts", time.time())
        row.pop("prompt", None)
        row.pop("message", None)
        row.pop("response", None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


class IrcModelChat:
    def __init__(self, adapter: LegacyConsoleAdapter | None = None) -> None:
        self.adapter = adapter or LegacyConsoleAdapter()

    def run(self, model_id: str, prompt: str, actor: dict[str, Any]) -> dict[str, Any]:
        allowed, guard = self.adapter.cost_control_guard("irc.chat", category="llm_service", actor=actor)
        if not allowed:
            return {"ok": False, "status": 402, "error": "cost_control_pause", "details": guard}
        payload = {
            "model": model_id,
            "client_selected_model_id": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
        }
        try:
            status, result = self.adapter.chat_completion(payload)
        except Exception as exc:
            return {"ok": False, "status": 500, "error": str(exc)}
        if int(status) >= 400:
            return {"ok": False, "status": int(status), "error": "model_request_failed", "details": result}
        normalized = normalize_chat_result(result, model_id)
        text = normalized.get("text") or normalized.get("content") or normalized.get("message") or normalized.get("answer") or ""
        cost = normalized.get("cost") if isinstance(normalized.get("cost"), dict) else {}
        trace = normalized.get("trace") if isinstance(normalized.get("trace"), dict) else {}
        return {
            "ok": True,
            "status": int(status),
            "text": str(text or "The model returned no readable text."),
            "cost": cost,
            "trace": trace,
            "routing": normalized.get("routing") if isinstance(normalized.get("routing"), dict) else {},
        }


class IrcClientSession:
    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        config: dict[str, Any],
        directory: IrcModelDirectory,
        chat: IrcModelChat,
        metadata_log: IrcMetadataLog,
        owner_token_provider: Callable[[], str] = owner_console_token,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.config = config
        self.directory = directory
        self.chat = chat
        self.metadata_log = metadata_log
        self.owner_token_provider = owner_token_provider
        self.nick = ""
        self.user = ""
        self.authenticated = False
        self.registered = False
        self.joined = False
        self.selected_model_ids: list[str] = []
        self.everyone_pending = False
        peer = writer.get_extra_info("peername")
        self.peer = "%s:%s" % peer[:2] if isinstance(peer, tuple) and len(peer) >= 2 else "unknown"

    async def send(self, line: str) -> None:
        self.writer.write((line + "\r\n").encode("utf-8", errors="replace"))
        await self.writer.drain()

    async def server_notice(self, text: str) -> None:
        target = self.nick or "*"
        for chunk in text_chunks(text):
            await self.send(f":{SERVER_NAME} NOTICE {target} :{chunk}")

    async def bot_reply(self, text: str, target: str | None = None) -> None:
        target = target or self.nick or DEFAULT_CHANNEL
        for chunk in text_chunks(text):
            await self.send(f":platform!service@{SERVER_NAME} PRIVMSG {target} :{chunk}")

    def actor(self) -> dict[str, Any]:
        return {
            "id": f"irc:{self.nick or self.peer}",
            "roles": ["owner"],
            "permissions": ["*"],
            "source": "irc",
        }

    def model_contacts(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        return self.directory.maps()

    def selected_models(self) -> list[dict[str, Any]]:
        _by_nick, by_id = self.model_contacts()
        rows = []
        for model_id in self.selected_model_ids:
            model = by_id.get(model_id.lower())
            if model:
                rows.append(model)
        return rows

    async def maybe_register(self) -> bool:
        if self.registered:
            return True
        if not (self.nick and self.user):
            return False
        if not self.authenticated:
            await self.send(f":{SERVER_NAME} 464 {self.nick} :Password incorrect or missing")
            self.writer.close()
            return False
        self.registered = True
        await self.send(f":{SERVER_NAME} 001 {self.nick} :Welcome to the Matts LLM IRC bridge")
        await self.send(f":{SERVER_NAME} 002 {self.nick} :Your host is {SERVER_NAME}")
        await self.join_channel(str(self.config.get("channel") or DEFAULT_CHANNEL))
        await self.bot_reply("Use !models to list LLM contacts, !select <model|all> to choose participants, or message a model nick directly.")
        return True

    async def join_channel(self, channel: str) -> None:
        if channel != self.config.get("channel"):
            channel = str(self.config.get("channel") or DEFAULT_CHANNEL)
        self.joined = True
        await self.send(f":{self.nick}!{self.user}@irc JOIN {channel}")
        await self.names(channel)

    async def names(self, channel: str) -> None:
        by_nick, _by_id = self.model_contacts()
        names = [self.nick, "platform", *[model["irc_nick"] for model in by_nick.values()]]
        await self.send(f":{SERVER_NAME} 353 {self.nick} = {channel} :{' '.join(names)}")
        await self.send(f":{SERVER_NAME} 366 {self.nick} {channel} :End of /NAMES list")

    async def list_channels(self) -> None:
        channel = str(self.config.get("channel") or DEFAULT_CHANNEL)
        await self.send(f":{SERVER_NAME} 321 {self.nick} Channel :Users Name")
        await self.send(f":{SERVER_NAME} 322 {self.nick} {channel} 1 :LLM contacts and group chat")
        await self.send(f":{SERVER_NAME} 323 {self.nick} :End of /LIST")

    async def who(self, target: str) -> None:
        channel = target if target.startswith("#") else str(self.config.get("channel") or DEFAULT_CHANNEL)
        by_nick, _by_id = self.model_contacts()
        rows = [("platform", "service", "Platform service bot"), *[(model["irc_nick"], "model", str(model.get("display_name") or model.get("id"))) for model in by_nick.values()]]
        for nick, user, label in rows:
            await self.send(f":{SERVER_NAME} 352 {self.nick} {channel} {user} {SERVER_NAME} {SERVER_NAME} {nick} H :0 {label}")
        await self.send(f":{SERVER_NAME} 315 {self.nick} {channel} :End of /WHO list")

    async def handle_pass(self, params: list[str]) -> None:
        token = params[0] if params else ""
        owner = self.owner_token_provider()
        self.authenticated = bool(token and owner and secrets.compare_digest(token, owner))
        if not self.authenticated:
            await self.send(f":{SERVER_NAME} 464 * :Password incorrect")
            self.writer.close()

    async def handle_command(self, command: str, params: list[str]) -> None:
        if command == "PASS":
            await self.handle_pass(params)
        elif command == "NICK":
            self.nick = irc_nick(params[0] if params else "", "remote")
            await self.maybe_register()
        elif command == "USER":
            self.user = irc_nick(params[0] if params else "remote", "remote")
            await self.maybe_register()
        elif command == "PING":
            await self.send(f":{SERVER_NAME} PONG {SERVER_NAME} :{params[-1] if params else SERVER_NAME}")
        elif not self.registered:
            await self.send(f":{SERVER_NAME} 451 * :Register first with PASS, NICK, and USER")
        elif command == "JOIN":
            await self.join_channel(params[0] if params else str(self.config.get("channel") or DEFAULT_CHANNEL))
        elif command == "PART":
            channel = params[0] if params else str(self.config.get("channel") or DEFAULT_CHANNEL)
            self.joined = False
            await self.send(f":{self.nick}!{self.user}@irc PART {channel}")
        elif command == "LIST":
            await self.list_channels()
        elif command == "NAMES":
            await self.names(params[0] if params else str(self.config.get("channel") or DEFAULT_CHANNEL))
        elif command == "WHO":
            await self.who(params[0] if params else str(self.config.get("channel") or DEFAULT_CHANNEL))
        elif command == "PRIVMSG":
            await self.privmsg(params[0] if params else "", params[1] if len(params) > 1 else "")
        elif command == "QUIT":
            self.writer.close()
        else:
            await self.send(f":{SERVER_NAME} 421 {self.nick} {command} :Unknown command")

    async def privmsg(self, target: str, message: str) -> None:
        if not message.strip():
            return
        lower_target = target.lower()
        by_nick, by_id = self.model_contacts()
        if lower_target == "platform" or message.startswith("!"):
            await self.platform_command(message, target if target.startswith("#") else self.nick)
            return
        if lower_target in by_nick:
            await self.chat_models([by_nick[lower_target]], target, message)
            return
        if lower_target in by_id:
            await self.chat_models([by_id[lower_target]], target, message)
            return
        channel = str(self.config.get("channel") or DEFAULT_CHANNEL).lower()
        if lower_target == channel:
            selected = self.selected_models()
            if not selected:
                await self.bot_reply("No model participants selected. Use !select <model> or !select all.", target)
                return
            await self.chat_models(selected, target, message)
            return
        await self.server_notice(f"Unknown target {target}. Use !models for available LLM contacts.")

    async def platform_command(self, message: str, target: str) -> None:
        text = message.strip()
        if not text.startswith("!"):
            await self.bot_reply("Use !help for bridge commands.", target)
            return
        parts = text.split()
        command = parts[0].lower()
        args = parts[1:]
        by_nick, by_id = self.model_contacts()
        if command == "!help":
            await self.bot_reply("Commands: !models, !select <model|all>, !participants, !clear, !everyone, !everyone confirm.", target)
        elif command == "!models":
            models = sorted(by_nick.values(), key=lambda row: str(row.get("irc_nick")).lower())
            if not models:
                await self.bot_reply("No routable text models are available.", target)
                return
            for model in models:
                await self.bot_reply(f"{model['irc_nick']} -> {model.get('id')} ({model.get('display_name') or model.get('company') or 'LLM'})", target)
        elif command == "!participants":
            rows = self.selected_models()
            names = ", ".join(str(row.get("irc_nick")) for row in rows)
            await self.bot_reply(f"Participants: {names or 'none'}", target)
        elif command == "!clear":
            self.selected_model_ids = []
            self.everyone_pending = False
            await self.bot_reply("Participants cleared.", target)
        elif command == "!everyone":
            if args and args[0].lower() == "confirm":
                models = list(by_nick.values())
                self.selected_model_ids = [str(row.get("id")) for row in models if row.get("id")]
                self.everyone_pending = False
                await self.bot_reply(f"All routable text models selected ({len(self.selected_model_ids)} participants).", target)
                return
            self.everyone_pending = True
            await self.bot_reply("This will send the next channel chats to every routable text model. Send !everyone confirm to enable.", target)
        elif command == "!select":
            selected = self.resolve_models(args, by_nick, by_id)
            if selected is None:
                await self.bot_reply("Selection not recognized. Use !models, !select <nick>, !select all, or !everyone confirm.", target)
                return
            self.selected_model_ids = [str(row.get("id")) for row in selected if row.get("id")]
            await self.bot_reply(f"Selected {len(self.selected_model_ids)} participant(s): {', '.join(str(row.get('irc_nick')) for row in selected)}", target)
        else:
            await self.bot_reply("Unknown command. Use !help.", target)

    def resolve_models(self, args: list[str], by_nick: dict[str, dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]] | None:
        if not args:
            return None
        raw = " ".join(args).replace(",", " ")
        names = [item.strip().lower() for item in raw.split() if item.strip()]
        if len(names) == 1 and names[0] in {"all", "everyone", "*"}:
            if names[0] == "everyone" and not self.everyone_pending:
                return None
            return list(by_nick.values())
        selected: list[dict[str, Any]] = []
        for name in names:
            model = by_nick.get(name) or by_id.get(name)
            if not model:
                return None
            if model not in selected:
                selected.append(model)
        return selected

    async def chat_models(self, models: list[dict[str, Any]], target: str, message: str) -> None:
        started = time.time()
        await self.bot_reply(f"Dispatching to {len(models)} model(s).", target if target.startswith("#") else self.nick)

        async def call(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float]:
            model_started = time.time()
            result = await asyncio.to_thread(self.chat.run, str(model.get("id") or ""), message, self.actor())
            return model, result, time.time() - model_started

        for model, result, elapsed in await asyncio.gather(*(call(model) for model in models)):
            model_id = str(model.get("id") or "")
            nick = str(model.get("irc_nick") or model_id or "model")
            status = "ok" if result.get("ok") else "error"
            self.metadata_log.append({
                "event": "irc.chat",
                "actor_id": self.actor()["id"],
                "client": self.peer,
                "target": target,
                "model_id": model_id,
                "status": status,
                "http_status": result.get("status"),
                "latency_ms": int(elapsed * 1000),
                "cost": result.get("cost") if isinstance(result.get("cost"), dict) else {},
                "trace": result.get("trace") if isinstance(result.get("trace"), dict) else {},
                "fanout": len(models),
            })
            if result.get("ok"):
                for chunk in text_chunks(str(result.get("text") or "")):
                    await self.send(f":{nick}!model@{SERVER_NAME} PRIVMSG {target if target.startswith('#') else self.nick} :{chunk}")
            else:
                await self.bot_reply(f"{nick} failed: {result.get('error') or 'request failed'}", target if target.startswith("#") else self.nick)
        self.metadata_log.append({
            "event": "irc.chat.batch",
            "actor_id": self.actor()["id"],
            "client": self.peer,
            "target": target,
            "model_count": len(models),
            "latency_ms": int((time.time() - started) * 1000),
        })

    async def run(self) -> None:
        await self.send(f":{SERVER_NAME} NOTICE * :PASS with the owner console token is required.")
        while not self.reader.at_eof():
            raw = await self.reader.readline()
            if not raw:
                break
            command, params = parse_irc_line(raw.decode("utf-8", errors="replace"))
            if command:
                await self.handle_command(command, params)


class IrcBridgeServer:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or IrcBridgeConfigStore().load()
        self.directory = IrcModelDirectory()
        self.chat = IrcModelChat()
        self.metadata_log = IrcMetadataLog(Path(str(self.config.get("metadata_log") or "")))

    def ssl_context(self) -> ssl.SSLContext | None:
        if not bool_value(self.config.get("tls_enabled")):
            return None
        cert_file = str(self.config.get("tls_cert_file") or "")
        key_file = str(self.config.get("tls_key_file") or "")
        if not cert_file or not key_file:
            raise RuntimeError("TLS is enabled but tls_cert_file or tls_key_file is missing")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        return context

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = IrcClientSession(
            reader=reader,
            writer=writer,
            config=self.config,
            directory=self.directory,
            chat=self.chat,
            metadata_log=self.metadata_log,
        )
        try:
            await session.run()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def serve_forever(self) -> None:
        host = str(self.config.get("host") or "0.0.0.0")
        port = int(self.config.get("port") or 6667)
        server = await asyncio.start_server(self.handle_client, host=host, port=port, ssl=self.ssl_context())
        sockets = ", ".join(str(sock.getsockname()) for sock in (server.sockets or []))
        print(f"IRC bridge listening on {sockets}", flush=True)
        async with server:
            await server.serve_forever()


class IrcBridgeManager:
    def __init__(self, store: IrcBridgeConfigStore | None = None) -> None:
        self.store = store or IrcBridgeConfigStore()

    def config(self) -> dict[str, Any]:
        return self.store.load()

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.save(payload)

    def command(self) -> list[str]:
        configured = os.environ.get("MATTS_IRC_BRIDGE_COMMAND", "").strip()
        if configured:
            return shlex.split(configured)
        script = PROJECT_DIR / "matts-irc-bridge.py"
        return [sys.executable or "python3", str(script), "supervise"]

    def tmux_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["TMUX_TMPDIR"] = str(tmux_tmpdir())
        env["PYTHONPATH"] = os.environ.get("PYTHONPATH") or str(PROJECT_DIR)
        return env

    def tmux(self, args: list[str]) -> tuple[int, str, str]:
        try:
            result = subprocess.run(["tmux", *args], text=True, capture_output=True, check=False, env=self.tmux_env())
        except FileNotFoundError:
            return 127, "", "tmux is not installed"
        return result.returncode, result.stdout, result.stderr

    def has_session(self, session_name: str | None = None) -> bool:
        name = session_name or str(self.config().get("session_name") or DEFAULT_SESSION_NAME)
        return self.tmux(["has-session", "-t", name])[0] == 0

    def capture(self, session_name: str | None = None, limit: int = 80) -> str:
        name = session_name or str(self.config().get("session_name") or DEFAULT_SESSION_NAME)
        code, out, err = self.tmux(["capture-pane", "-pt", name, "-S", f"-{int(limit)}"])
        return out if code == 0 else err.strip()

    def listening(self, config: dict[str, Any] | None = None) -> bool:
        cfg = config or self.config()
        host = "127.0.0.1" if str(cfg.get("host") or "") in {"0.0.0.0", "::"} else str(cfg.get("host") or "127.0.0.1")
        port = int(cfg.get("port") or 6667)
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            return False

    def status(self) -> dict[str, Any]:
        config = self.config()
        session_name = str(config.get("session_name") or DEFAULT_SESSION_NAME)
        tmux_running = self.has_session(session_name)
        return {
            "generated_at": time.time(),
            "config": config,
            "tmux": {
                "session_name": session_name,
                "running": tmux_running,
                "tmux_tmpdir": str(tmux_tmpdir()),
                "tail": self.capture(session_name) if tmux_running else "",
            },
            "listening": self.listening(config),
            "models": IrcModelDirectory().models(),
            "metadata_log": str(config.get("metadata_log") or self.store.metadata_path),
        }

    def ensure_tmux(self) -> dict[str, Any]:
        config = self.config()
        if not bool_value(config.get("enabled"), True):
            return {"ok": False, "skipped": True, "reason": "irc bridge disabled", "status": self.status()}
        session_name = str(config.get("session_name") or DEFAULT_SESSION_NAME)
        if self.has_session(session_name):
            return {"ok": True, "changed": False, "status": self.status()}
        cmd = self.command()
        quoted = " ".join(shlex.quote(part) for part in cmd)
        code, out, err = self.tmux(["new-session", "-d", "-s", session_name, quoted])
        if code != 0:
            return {"ok": False, "changed": False, "error": err or out, "status": self.status()}
        return {"ok": True, "changed": True, "status": self.status()}

    def stop(self) -> dict[str, Any]:
        session_name = str(self.config().get("session_name") or DEFAULT_SESSION_NAME)
        code, out, err = self.tmux(["kill-session", "-t", session_name])
        if code not in {0, 1}:
            return {"ok": False, "error": err or out, "status": self.status()}
        return {"ok": True, "status": self.status()}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.ensure_tmux()


async def serve() -> None:
    await IrcBridgeServer().serve_forever()


def supervise(stop_event: Callable[[], bool] | None = None) -> int:
    stop_event = stop_event or (lambda: False)
    while not stop_event():
        config = IrcBridgeConfigStore().load()
        if not bool_value(config.get("enabled"), True):
            print("IRC bridge disabled; supervisor exiting.", flush=True)
            return 0
        try:
            asyncio.run(IrcBridgeServer(config).serve_forever())
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"IRC bridge crashed: {exc}", file=sys.stderr, flush=True)
            time.sleep(int(config.get("restart_delay_seconds") or 2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Matts LLM IRC bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the IRC bridge server in the foreground")
    sub.add_parser("supervise", help="run the IRC bridge with restart-on-failure")
    sub.add_parser("ensure-tmux", help="start the supervised bridge in tmux if enabled")
    sub.add_parser("stop", help="stop the bridge tmux session")
    sub.add_parser("restart", help="restart the bridge tmux session")
    sub.add_parser("status", help="print bridge status as JSON")
    args = parser.parse_args(argv)
    manager = IrcBridgeManager()
    if args.command == "serve":
        asyncio.run(IrcBridgeServer().serve_forever())
        return 0
    if args.command == "supervise":
        return supervise()
    if args.command == "ensure-tmux":
        print(json.dumps(manager.ensure_tmux(), indent=2, sort_keys=True))
        return 0
    if args.command == "stop":
        print(json.dumps(manager.stop(), indent=2, sort_keys=True))
        return 0
    if args.command == "restart":
        print(json.dumps(manager.restart(), indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        print(json.dumps(manager.status(), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    raise SystemExit(main())
