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
