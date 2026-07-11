"""Local document indexing and lexical retrieval for console grounding."""
import fnmatch
import hashlib
import json
import re
import time
from pathlib import Path


class LocalRagService:
    """Index configured local documents and return cited snippets."""

    schema_version = 1
    runtime_excludes = {
        ".git/*",
        ".cache/*",
        "build/*",
        "dist/*",
        "frontend/node_modules/*",
        "frontend/dist/*",
        "**/__pycache__/*",
        "**/*.pyc",
        "**/.env",
        "**/*token*",
        "**/*secret*",
        "**/*key*",
    }
    text_suffixes = {".md", ".txt", ".json", ".py", ".js", ".ts", ".tsx", ".html", ".css", ".sh", ".yml", ".yaml"}

    def __init__(self, project_dir, config_file, index_file, clock=None):
        self.project_dir = Path(project_dir).resolve()
        self.config_file = config_file
        self.index_file = index_file
        self.clock = clock or time.time

    def default_config(self):
        return {
            "schema_version": self.schema_version,
            "collections": [
                {
                    "id": "project-docs",
                    "name": "Project Docs",
                    "include": ["README.md", "GOVERNANCE.md", "MAIN-WORKLIST.md", "docs/**/*.md"],
                    "exclude": [],
                    "max_file_bytes": 250000,
                }
            ],
        }

    def load_config(self):
        path = self.config_file()
        if not path.exists():
            return self.default_config()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.default_config()
        if not isinstance(data, dict) or data.get("schema_version") != self.schema_version:
            return self.default_config()
        if not isinstance(data.get("collections"), list):
            data["collections"] = []
        return data

    def save_config(self, data):
        data = data if isinstance(data, dict) else {}
        collections = data.get("collections") if isinstance(data.get("collections"), list) else []
        normalized = {"schema_version": self.schema_version, "collections": []}
        for item in collections:
            if not isinstance(item, dict):
                continue
            collection_id = str(item.get("id") or item.get("name") or "").strip()
            if not collection_id:
                continue
            normalized["collections"].append({
                "id": collection_id,
                "name": str(item.get("name") or collection_id),
                "include": [str(x) for x in (item.get("include") or []) if str(x or "").strip()],
                "exclude": [str(x) for x in (item.get("exclude") or []) if str(x or "").strip()],
                "max_file_bytes": int(item.get("max_file_bytes") or 250000),
            })
        if not normalized["collections"]:
            normalized = self.default_config()
        path = self.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return normalized

    def load_index(self):
        path = self.index_file()
        if not path.exists():
            return {"schema_version": self.schema_version, "collections": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema_version": self.schema_version, "collections": {}}
        return data if isinstance(data, dict) else {"schema_version": self.schema_version, "collections": {}}

    def path_key(self, path):
        try:
            return path.resolve().relative_to(self.project_dir).as_posix()
        except ValueError:
            return ""

    def blocked_path(self, rel, excludes):
        patterns = list(self.runtime_excludes) + list(excludes or [])
        return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch("/" + rel, pattern) for pattern in patterns)

    def iter_files(self, collection):
        include = collection.get("include") or []
        excludes = collection.get("exclude") or []
        seen = set()
        for pattern in include:
            for path in self.project_dir.glob(pattern):
                if not path.is_file():
                    continue
                rel = self.path_key(path)
                if not rel or rel in seen or self.blocked_path(rel, excludes):
                    continue
                if path.suffix.lower() not in self.text_suffixes:
                    continue
                try:
                    if path.stat().st_size > int(collection.get("max_file_bytes") or 250000):
                        continue
                except OSError:
                    continue
                seen.add(rel)
                yield path, rel

    def chunks(self, text, max_chars=900):
        parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        chunks = []
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 <= max_chars:
                current = (current + "\n\n" + part).strip()
            else:
                if current:
                    chunks.append(current)
                current = part[:max_chars]
        if current:
            chunks.append(current)
        return chunks or [text[:max_chars]]

    def index(self, request=None):
        request = request if isinstance(request, dict) else {}
        config = self.load_config()
        selected = str(request.get("collection_id") or "").strip()
        collections = [c for c in config.get("collections", []) if not selected or c.get("id") == selected]
        index = self.load_index()
        index.setdefault("schema_version", self.schema_version)
        index.setdefault("collections", {})
        summaries = []
        for collection in collections:
            docs = []
            for path, rel in self.iter_files(collection):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for chunk_index, chunk in enumerate(self.chunks(text), start=1):
                    docs.append({
                        "id": hashlib.sha256(("%s:%s:%s" % (collection["id"], rel, chunk_index)).encode("utf-8")).hexdigest()[:16],
                        "path": rel,
                        "chunk": chunk_index,
                        "text": chunk,
                        "tokens_est": max(1, len(chunk.split())),
                        "hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16],
                    })
            index["collections"][collection["id"]] = {
                "id": collection["id"],
                "name": collection.get("name") or collection["id"],
                "indexed_at": self.clock(),
                "documents": docs,
            }
            summaries.append({"id": collection["id"], "documents": len(docs), "files": len(set(doc["path"] for doc in docs))})
        path = self.index_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"indexed": summaries, "generated_at": self.clock()}

    def terms(self, text):
        return [term for term in re.findall(r"[a-zA-Z0-9_]{3,}", str(text or "").lower()) if term not in {"the", "and", "for", "with", "that", "this"}]

    def search(self, request):
        request = request if isinstance(request, dict) else {}
        query = str(request.get("query") or "").strip()
        if not query:
            return {"query": "", "matches": [], "collections": []}
        collection_id = str(request.get("collection_id") or request.get("collection") or "project-docs")
        try:
            limit = max(1, min(12, int(request.get("limit") or 5)))
        except (TypeError, ValueError):
            limit = 5
        index = self.load_index()
        collections = index.get("collections") if isinstance(index.get("collections"), dict) else {}
        selected = [collections[collection_id]] if collection_id in collections else list(collections.values())
        query_terms = set(self.terms(query))
        scored = []
        for collection in selected:
            for doc in collection.get("documents") or []:
                text = str(doc.get("text") or "")
                doc_terms = set(self.terms(text))
                overlap = len(query_terms & doc_terms)
                if not overlap and query.lower() not in text.lower():
                    continue
                score = overlap * 10 + (5 if query.lower() in text.lower() else 0)
                scored.append({
                    "score": score,
                    "collection_id": collection.get("id"),
                    "collection_name": collection.get("name"),
                    "path": doc.get("path"),
                    "chunk": doc.get("chunk"),
                    "text": text[:900],
                    "tokens_est": doc.get("tokens_est"),
                    "hash": doc.get("hash"),
                })
        scored.sort(key=lambda item: (item["score"], item["path"] or ""), reverse=True)
        return {"query": query, "collection_id": collection_id, "matches": scored[:limit], "collections": list(collections.keys())}

    def context_text(self, matches):
        lines = ["Local retrieval context. Use only when relevant and cite sources by [path#chunk]."]
        for item in matches:
            lines.append("[%s#%s] %s" % (item.get("path"), item.get("chunk"), item.get("text")))
        return "\n\n".join(lines)

    def augment(self, data, action="chat"):
        data = dict(data or {})
        retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
        if not retrieval.get("enabled"):
            return {"data": data, "retrieval": {"enabled": False, "matches": []}}
        query = retrieval.get("query") or data.get("prompt") or ""
        if not query:
            messages = data.get("messages") if isinstance(data.get("messages"), list) else []
            for message in reversed(messages):
                if isinstance(message, dict) and message.get("role") == "user":
                    query = message.get("content") or ""
                    break
        result = self.search({
            "query": query,
            "collection_id": retrieval.get("collection_id") or retrieval.get("collection") or "project-docs",
            "limit": retrieval.get("limit") or 5,
        })
        matches = result.get("matches") or []
        if not matches:
            data["retrieval_context"] = {"enabled": True, "matches": []}
            return {"data": data, "retrieval": data["retrieval_context"]}
        context = self.context_text(matches)
        if action in {"code", "tmux"}:
            prompt = str(data.get("print_prompt") or "").strip()
            data["print_prompt"] = (context + "\n\nTask:\n" + prompt).strip()
        else:
            messages = list(data.get("messages") if isinstance(data.get("messages"), list) else [])
            messages.insert(0, {"role": "system", "content": context, "meta": {"retrieval": True}})
            data["messages"] = messages
        data["retrieval_context"] = {"enabled": True, "query": result.get("query"), "matches": matches}
        return {"data": data, "retrieval": data["retrieval_context"]}

    def payload(self):
        config = self.load_config()
        index = self.load_index()
        summaries = []
        for cid, collection in (index.get("collections") or {}).items():
            docs = collection.get("documents") or []
            summaries.append({"id": cid, "name": collection.get("name"), "documents": len(docs), "files": len(set(doc.get("path") for doc in docs)), "indexed_at": collection.get("indexed_at")})
        return {"config": config, "index": summaries, "runtime_excludes": sorted(self.runtime_excludes)}
