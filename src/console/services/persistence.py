"""Local image-history and chat persistence helpers."""
import base64
import json
import mimetypes
import time
import uuid
from urllib.request import urlopen


class LocalPersistenceService:
    """Owns local JSONL history, image files, and saved chat documents."""

    def __init__(self, app_dir, chat_cost_per_mtok, default_text_model, clock=None, uuid_factory=None):
        self.app_dir = app_dir
        self.chat_cost_per_mtok = chat_cost_per_mtok
        self.default_text_model = default_text_model
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def history_path(self):
        return self.app_dir() / "history.jsonl"

    def read_history(self, limit=300):
        rows = []
        path = self.history_path()
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        rows.sort(key=lambda item: item.get("created_at", 0), reverse=True)
        return rows[:limit]

    def append_history(self, record):
        with self.history_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def save_image_item(self, item, image_id):
        image_dir = self.app_dir() / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            data = base64.b64decode(item["b64_json"])
            ext = ".png"
        elif item.get("url"):
            with urlopen(item["url"], timeout=240) as resp:
                data = resp.read()
                ext = mimetypes.guess_extension(resp.headers.get_content_type()) or ".png"
        else:
            raise ValueError("image response did not include b64_json or url")
        out = image_dir / ("%s%s" % (image_id, ext))
        out.write_bytes(data)
        return out

    def delete_history_item(self, image_id):
        path = self.history_path()
        if not path.exists():
            return False
        original = self.read_history(limit=100000)
        kept = []
        removed = None
        for row in original:
            if row.get("id") == image_id:
                removed = row
            else:
                kept.append(row)
        with path.open("w", encoding="utf-8") as f:
            for row in reversed(kept):
                f.write(json.dumps(row, sort_keys=True) + "\n")
        if removed:
            try:
                (self.app_dir() / "images" / removed["filename"]).unlink()
            except OSError:
                pass
        return bool(removed)

    def chats_dir(self):
        path = self.app_dir() / "chats"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def estimate_tokens(self, text):
        return max(1, int(len(str(text or "").split()) * 1.3))

    def chat_cost_usd(self, model, input_text, output_text):
        rates = self.chat_cost_per_mtok.get(model, {})
        in_tokens = self.estimate_tokens(input_text)
        out_tokens = self.estimate_tokens(output_text)
        in_cost = in_tokens * float(rates.get("input", 0.0)) / 1_000_000
        out_cost = out_tokens * float(rates.get("output", 0.0)) / 1_000_000
        return {
            "input_tokens_est": in_tokens,
            "output_tokens_est": out_tokens,
            "total_tokens_est": in_tokens + out_tokens,
            "input_cost_usd": round(in_cost, 8),
            "output_cost_usd": round(out_cost, 8),
            "total_cost_usd": round(in_cost + out_cost, 8),
        }

    def chat_filename(self, chat_id):
        return self.chats_dir() / ("chat_%s.json" % chat_id)

    def make_title(self, messages):
        for msg in (messages or []):
            if msg.get("role") == "user":
                text = str(msg.get("content") or "").strip()
                if text:
                    return text[:60]
        return "Untitled"

    def save_chat(self, data):
        now = self.clock()
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        model = data.get("model") or self.default_text_model()
        chat_id = data.get("id") or ("chat_%d_%s" % (now, self.uuid_factory().hex[:12]))
        title = data.get("title") or self.make_title(messages)
        branch = data.get("branch") if isinstance(data.get("branch"), dict) else {}

        for msg in messages:
            if not msg.get("timestamp"):
                msg["timestamp"] = now
            if not msg.get("tokens"):
                msg["tokens"] = self.estimate_tokens(msg.get("content") or "")

        running_cost = 0.0
        in_text = ""
        for msg in messages:
            if msg.get("role") == "user":
                in_text += (msg.get("content") or "") + " "
            elif msg.get("role") == "assistant":
                out_text = msg.get("content") or ""
                cost_info = self.chat_cost_usd(model, in_text, out_text)
                running_cost += cost_info["total_cost_usd"]
                in_text = ""

        running_tokens = sum(int(m.get("tokens", 0)) for m in messages)
        doc = {
            "id": chat_id,
            "created_at": data.get("created_at") or now,
            "updated_at": now,
            "model": model,
            "messages": messages,
            "title": title,
            "total_tokens": running_tokens,
            "total_cost_usd": round(running_cost, 8),
        }
        if branch:
            doc["branch"] = branch
        path = self.chat_filename(chat_id)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return doc

    def list_chats(self):
        result = []
        directory = self.chats_dir()
        for path in sorted(directory.glob("chat_*.json"), reverse=True):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            result.append({
                "id": doc.get("id", path.stem),
                "title": doc.get("title", "Untitled")[:60],
                "model": doc.get("model", ""),
                "created_at": doc.get("created_at", 0),
                "updated_at": doc.get("updated_at", doc.get("created_at", 0)),
                "message_count": len(doc.get("messages") or []),
                "total_cost_usd": doc.get("total_cost_usd", 0),
                "branch": doc.get("branch") if isinstance(doc.get("branch"), dict) else {},
            })
        return result

    def load_chat(self, chat_id):
        path = self.chat_filename(chat_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def delete_chat(self, chat_id):
        path = self.chat_filename(chat_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def fork_chat(self, data):
        data = data if isinstance(data, dict) else {}
        source_id = data.get("source_chat_id") or data.get("id")
        source = self.load_chat(source_id)
        if source is None:
            raise ValueError("source chat not found")
        messages = source.get("messages") if isinstance(source.get("messages"), list) else []
        try:
            index = int(data.get("message_index"))
        except (TypeError, ValueError):
            index = len(messages) - 1
        index = max(0, min(index, len(messages) - 1)) if messages else 0
        forked = [dict(message) for message in messages[:index + 1]]
        now = self.clock()
        source_message = messages[index] if messages and isinstance(messages[index], dict) else {}
        source_meta = source_message.get("meta") if isinstance(source_message.get("meta"), dict) else {}
        source_trace = source_meta.get("trace") if isinstance(source_meta.get("trace"), dict) else {}
        source_route = source_meta.get("routing") if isinstance(source_meta.get("routing"), dict) else {}
        source_cost = source_meta.get("cost") if isinstance(source_meta.get("cost"), dict) else {}
        model = data.get("model") or source.get("model") or self.default_text_model()
        branch = {
            "parent_chat_id": source.get("id"),
            "source_message_index": index,
            "source_trace_id": source_trace.get("trace_id"),
            "source_model": source_message.get("model") or source_meta.get("model") or source.get("model"),
            "source_route": source_route,
            "source_cost": source_cost,
            "source_latency_ms": source_trace.get("latency_ms") or source_meta.get("latency_ms"),
            "selected_model": model,
            "forked_at": now,
            "notes": str(data.get("notes") or ""),
            "prompt_profile": str(data.get("prompt_profile") or ""),
            "gateway_policy": data.get("gateway_policy") if isinstance(data.get("gateway_policy"), dict) else {},
        }
        title = data.get("title") or ("%s branch @ %s" % (source.get("title") or "Chat", index))
        return self.save_chat({
            "model": model,
            "messages": forked,
            "title": title,
            "branch": branch,
            "created_at": now,
        })

    def branch_comparison(self, chat_id):
        parent = self.load_chat(chat_id)
        parent_messages = parent.get("messages") if isinstance(parent, dict) and isinstance(parent.get("messages"), list) else []
        parent_last = parent_messages[-1] if parent_messages else {}
        parent_text = str(parent_last.get("content") or "")
        branches = []
        for item in self.list_chats():
            branch = item.get("branch") if isinstance(item.get("branch"), dict) else {}
            if branch.get("parent_chat_id") == chat_id:
                doc = self.load_chat(item["id"]) or item
                messages = doc.get("messages") or []
                last = messages[-1] if messages else {}
                meta = last.get("meta") if isinstance(last.get("meta"), dict) else {}
                trace = meta.get("trace") if isinstance(meta.get("trace"), dict) else {}
                route = meta.get("routing") if isinstance(meta.get("routing"), dict) else {}
                cost = meta.get("cost") if isinstance(meta.get("cost"), dict) else {}
                branch_text = str(last.get("content") or "")
                shared_prefix = 0
                for left, right in zip(parent_text, branch_text):
                    if left != right:
                        break
                    shared_prefix += 1
                branches.append({
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "model": doc.get("model"),
                    "message_count": len(messages),
                    "total_cost_usd": doc.get("total_cost_usd", 0),
                    "updated_at": doc.get("updated_at"),
                    "branch": doc.get("branch") or {},
                    "metrics": {
                        "model": last.get("model") or meta.get("model") or doc.get("model"),
                        "route": route,
                        "cost": cost,
                        "latency_ms": trace.get("latency_ms") or meta.get("latency_ms"),
                        "notes": branch.get("notes", ""),
                    },
                    "diff": {
                        "shared_prefix_chars": shared_prefix,
                        "branch_delta_chars": len(branch_text) - len(parent_text),
                        "parent_preview": parent_text[:240],
                        "branch_preview": branch_text[:240],
                    },
                    "last_message": {
                        "role": last.get("role"),
                        "preview": str(last.get("content") or "")[:240],
                        "model": last.get("model") or meta.get("model"),
                        "routing": route,
                        "cost": cost,
                        "trace": trace,
                        "streaming_metrics": meta.get("streaming_metrics") or {},
                    },
                })
        return {"parent": parent, "branches": branches}
