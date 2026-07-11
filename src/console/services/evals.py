"""Local evaluation dataset and run helpers."""
import json
import time
import uuid


class EvalService:
    """Run small local prompt/model evals through the existing chat router."""

    schema_version = 1

    def __init__(self, evals_dir, runs_dir, chat_completion, active_text_models, default_text_model, retrieval_augment=None, clock=None, uuid_factory=None):
        self.evals_dir = evals_dir
        self.runs_dir = runs_dir
        self.chat_completion = chat_completion
        self.active_text_models = active_text_models
        self.default_text_model = default_text_model
        self.retrieval_augment = retrieval_augment or (lambda data, action="eval": {"data": data, "retrieval": {"enabled": False, "matches": []}})
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def dataset_dir(self):
        path = self.evals_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run_dir(self):
        path = self.runs_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def dataset_path(self, dataset_id):
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(dataset_id or ""))
        return self.dataset_dir() / ("%s.json" % safe)

    def run_path(self, run_id):
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(run_id or ""))
        return self.run_dir() / ("%s.json" % safe)

    def normalize_dataset(self, data, source=""):
        if not isinstance(data, dict):
            raise ValueError("Eval dataset must be a JSON object.")
        examples = data.get("examples")
        if not isinstance(examples, list) or not examples:
            raise ValueError("Eval dataset must include at least one example.")
        dataset_id = str(data.get("id") or data.get("name") or "dataset").strip()
        normalized = {
            "schema_version": int(data.get("schema_version") or self.schema_version),
            "id": dataset_id,
            "name": str(data.get("name") or dataset_id),
            "description": str(data.get("description") or ""),
            "source": source,
            "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            "examples": [],
        }
        if normalized["schema_version"] != self.schema_version:
            raise ValueError("Eval dataset schema_version %s is not supported." % normalized["schema_version"])
        for index, example in enumerate(examples, start=1):
            if not isinstance(example, dict):
                raise ValueError("Eval example %s must be an object." % index)
            prompt = str(example.get("input") or example.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("Eval example %s is missing input." % index)
            normalized["examples"].append({
                "id": str(example.get("id") or "ex-%03d" % index),
                "input": prompt,
                "expected": str(example.get("expected") or ""),
                "tags": list(example.get("tags") or []),
                "notes": str(example.get("notes") or ""),
                "metadata": example.get("metadata") if isinstance(example.get("metadata"), dict) else {},
            })
        return normalized

    def save_dataset(self, data):
        dataset = self.normalize_dataset(data)
        dataset["source"] = "builder"
        dataset["updated_at"] = self.clock()
        path = self.dataset_path(dataset["id"])
        path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.normalize_dataset(json.loads(path.read_text(encoding="utf-8")), source=str(path))

    def build_dataset(self, request):
        request = request if isinstance(request, dict) else {}
        raw_examples = request.get("examples") if isinstance(request.get("examples"), list) else []
        if not raw_examples:
            raise ValueError("Dataset builder requires at least one example.")
        examples = []
        for index, item in enumerate(raw_examples, start=1):
            examples.append(self.build_example(item, index))
        return self.save_dataset({
            "id": request.get("id") or request.get("name") or "builder-dataset",
            "name": request.get("name") or request.get("id") or "Builder Dataset",
            "description": request.get("description") or "",
            "metadata": {
                "builder": "console",
                "source_types": sorted({example["metadata"].get("source_type", "manual") for example in examples}),
                "operator_notes": str(request.get("operator_notes") or ""),
            },
            "examples": examples,
        })

    def build_example(self, item, index):
        if not isinstance(item, dict):
            raise ValueError("Dataset builder example %s must be an object." % index)
        source_type = str(item.get("source_type") or "manual").strip().lower()
        if source_type not in {"manual", "trace", "chat", "comparison"}:
            raise ValueError("Dataset builder example %s has unsupported source_type." % index)
        if source_type != "manual" and not item.get("redaction_reviewed"):
            raise ValueError("Dataset builder example %s requires redaction_reviewed before saving runtime data." % index)
        prompt = str(item.get("input") or item.get("prompt") or "").strip()
        if not prompt and source_type == "trace":
            trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
            summary = trace.get("message_summary") if isinstance(trace.get("message_summary"), dict) else {}
            prompt = str(summary.get("last_user_preview") or "").strip()
        if not prompt:
            raise ValueError("Dataset builder example %s is missing reviewed input." % index)
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
        chat = item.get("chat") if isinstance(item.get("chat"), dict) else {}
        comparison = item.get("comparison") if isinstance(item.get("comparison"), dict) else {}
        metadata = {
            "source_type": source_type,
            "redaction_reviewed": bool(item.get("redaction_reviewed") or source_type == "manual"),
            "source_trace_id": item.get("trace_id") or trace.get("trace_id") or source.get("trace_id"),
            "source_chat_id": item.get("chat_id") or chat.get("id") or source.get("chat_id"),
            "source_message_index": item.get("message_index") if item.get("message_index") is not None else source.get("message_index"),
            "requested_model": item.get("requested_model") or trace.get("requested_model") or comparison.get("requested_model"),
            "routed_model": item.get("routed_model") or trace.get("routed_model") or comparison.get("routed_model"),
            "routing_reason": item.get("routing_reason") or trace.get("routing_reason") or comparison.get("routing_reason"),
            "cost_usd": item.get("cost_usd") if item.get("cost_usd") is not None else trace.get("cost_usd"),
        }
        metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
        return {
            "id": str(item.get("id") or "ex-%03d" % index),
            "input": prompt,
            "expected": str(item.get("expected") or ""),
            "tags": list(item.get("tags") or []),
            "notes": str(item.get("notes") or ""),
            "metadata": metadata,
        }

    def list_datasets(self):
        rows = []
        for path in sorted(self.dataset_dir().glob("*.json")):
            try:
                dataset = self.normalize_dataset(json.loads(path.read_text(encoding="utf-8")), source=str(path))
            except (OSError, ValueError, TypeError) as exc:
                rows.append({"id": path.stem, "name": path.stem, "valid": False, "error": str(exc), "source": str(path), "example_count": 0})
                continue
            rows.append({
                "id": dataset["id"],
                "name": dataset["name"],
                "description": dataset["description"],
                "valid": True,
                "source": str(path),
                "example_count": len(dataset["examples"]),
                "metadata": dataset.get("metadata") or {},
            })
        return rows

    def load_dataset(self, dataset_id):
        path = self.dataset_path(dataset_id)
        if not path.exists():
            raise ValueError("Eval dataset '%s' was not found." % dataset_id)
        return self.normalize_dataset(json.loads(path.read_text(encoding="utf-8")), source=str(path))

    def score_answer(self, expected, answer):
        expected = str(expected or "").strip().lower()
        answer = str(answer or "").strip().lower()
        if not expected:
            return {"score": None, "passed": None, "method": "unscored"}
        if expected == answer:
            return {"score": 1.0, "passed": True, "method": "exact"}
        if expected in answer:
            return {"score": 0.75, "passed": True, "method": "contains"}
        return {"score": 0.0, "passed": False, "method": "contains"}

    def run(self, request):
        request = request or {}
        dataset = self.load_dataset(request.get("dataset_id") or "smoke")
        active = set(self.active_text_models())
        models = request.get("models") or [self.default_text_model()]
        models = [str(model) for model in models if str(model or "").strip()]
        if not models:
            raise ValueError("Select at least one model for the eval run.")
        unavailable = [model for model in models if model not in active]
        if unavailable:
            raise ValueError("Unavailable eval models: " + ", ".join(unavailable))
        max_examples = int(request.get("max_examples") or len(dataset["examples"]))
        examples = dataset["examples"][:max(1, max_examples)]
        started = self.clock()
        run_id = "eval_%d_%s" % (started, self.uuid_factory().hex[:10])
        results = []
        summaries = {model: {"model": model, "requests": 0, "failures": 0, "total_cost_usd": 0.0, "total_latency_ms": 0, "passes": 0, "scored": 0} for model in models}
        for example in examples:
            row = {"example_id": example["id"], "input": example["input"], "expected": example.get("expected") or "", "responses": []}
            for model in models:
                req_started = self.clock()
                chat_request = {"model": model, "messages": [{"role": "user", "content": example["input"]}], "max_tokens": request.get("max_tokens") or 512, "temperature": request.get("temperature", "")}
                if isinstance(request.get("retrieval"), dict):
                    chat_request["retrieval"] = request.get("retrieval")
                    augmented = self.retrieval_augment(chat_request, action="eval")
                    chat_request = augmented.get("data") or chat_request
                    row["retrieval"] = augmented.get("retrieval")
                status, payload = self.chat_completion(chat_request)
                latency_ms = int(max(0, (self.clock() - req_started) * 1000))
                text = payload.get("text") if isinstance(payload, dict) else ""
                score = self.score_answer(example.get("expected"), text)
                cost = payload.get("cost") if isinstance(payload, dict) and isinstance(payload.get("cost"), dict) else {}
                response = {
                    "model": model,
                    "status": int(status),
                    "ok": int(status) < 400,
                    "answer": text or "",
                    "latency_ms": latency_ms,
                    "cost_usd": float(cost.get("total_cost_usd") or 0.0),
                    "usage": payload.get("usage") if isinstance(payload, dict) else {},
                    "trace_id": payload.get("trace_id") if isinstance(payload, dict) else "",
                    "error": (payload.get("message") or payload.get("error") or "") if isinstance(payload, dict) and int(status) >= 400 else "",
                    "score": score,
                }
                summaries[model]["requests"] += 1
                summaries[model]["failures"] += 0 if response["ok"] else 1
                summaries[model]["total_cost_usd"] += response["cost_usd"]
                summaries[model]["total_latency_ms"] += latency_ms
                if score["score"] is not None:
                    summaries[model]["scored"] += 1
                    summaries[model]["passes"] += 1 if score["passed"] else 0
                row["responses"].append(response)
            row["selected_answer"] = self.select_answer(row["responses"])
            results.append(row)
        for summary in summaries.values():
            requests = max(1, summary["requests"])
            summary["avg_latency_ms"] = int(summary["total_latency_ms"] / requests)
            summary["total_cost_usd"] = round(summary["total_cost_usd"], 8)
            summary["pass_rate"] = round(summary["passes"] / summary["scored"], 4) if summary["scored"] else None
        doc = {
            "schema_version": self.schema_version,
            "id": run_id,
            "created_at": started,
            "dataset": {key: dataset[key] for key in ("id", "name", "description", "source")},
            "models": models,
            "example_count": len(examples),
            "results": results,
            "summary": list(summaries.values()),
            "baseline": self.compare_baseline(request.get("baseline_run_id"), summaries),
        }
        if isinstance(request.get("change_gate"), dict):
            gate = request.get("change_gate") or {}
            doc["change_gate"] = {
                "surface": str(gate.get("surface") or ""),
                "change_hash": str(gate.get("change_hash") or gate.get("hash") or ""),
                "target_id": str(gate.get("target_id") or ""),
                "target_version": int(gate.get("target_version") or 0),
            }
        self.run_path(run_id).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return doc

    def select_answer(self, responses):
        ok = [r for r in responses if r.get("ok")]
        if not ok:
            return None
        scored = [r for r in ok if (r.get("score") or {}).get("score") is not None]
        if scored:
            return max(scored, key=lambda r: ((r.get("score") or {}).get("score") or 0, -r.get("latency_ms", 0))).get("model")
        return min(ok, key=lambda r: (r.get("cost_usd", 0), r.get("latency_ms", 0))).get("model")

    def compare_baseline(self, baseline_run_id, summaries):
        if not baseline_run_id:
            return {}
        path = self.run_path(baseline_run_id)
        if not path.exists():
            return {"error": "baseline run not found", "id": baseline_run_id}
        try:
            baseline = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"error": str(exc), "id": baseline_run_id}
        previous = {row.get("model"): row for row in baseline.get("summary") or []}
        deltas = []
        for model, current in summaries.items():
            old = previous.get(model)
            if not old:
                continue
            deltas.append({
                "model": model,
                "cost_delta_usd": round(float(current.get("total_cost_usd") or 0) - float(old.get("total_cost_usd") or 0), 8),
                "failure_delta": int(current.get("failures") or 0) - int(old.get("failures") or 0),
                "latency_delta_ms": int(current.get("avg_latency_ms") or 0) - int(old.get("avg_latency_ms") or 0),
                "pass_rate_delta": None if current.get("pass_rate") is None or old.get("pass_rate") is None else round(float(current["pass_rate"]) - float(old["pass_rate"]), 4),
            })
        return {"id": baseline_run_id, "deltas": deltas}

    def list_runs(self, limit=20):
        rows = []
        for path in sorted(self.run_dir().glob("eval_*.json"), reverse=True):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append({
                "id": doc.get("id") or path.stem,
                "created_at": doc.get("created_at", 0),
                "dataset": (doc.get("dataset") or {}).get("name") or "",
                "models": doc.get("models") or [],
                "example_count": doc.get("example_count") or 0,
                "summary": doc.get("summary") or [],
                "change_gate": doc.get("change_gate") if isinstance(doc.get("change_gate"), dict) else {},
            })
            if len(rows) >= int(limit or 20):
                break
        return rows
