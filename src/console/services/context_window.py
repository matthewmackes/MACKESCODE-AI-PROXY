"""Approximate context window inspection for text-model actions."""
import math
import time


class ContextWindowService:
    """Estimate prompt footprint against registry context metadata."""

    def __init__(self, model_registry, default_text_model, load_eval_dataset=None, clock=None):
        self.model_registry = model_registry
        self.default_text_model = default_text_model
        self.load_eval_dataset = load_eval_dataset or (lambda dataset_id: {"examples": []})
        self.clock = clock or time.time

    def models(self):
        rows = self.model_registry() if callable(self.model_registry) else self.model_registry
        result = {}
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            result[str(row["id"])] = row
            for alias in row.get("aliases") or []:
                result[str(alias)] = row
        return result

    def message_text(self, message):
        if not isinstance(message, dict):
            return str(message or "")
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item or ""))
            return " ".join(parts)
        return str(content or "")

    def token_estimate(self, text):
        text = str(text or "")
        words = len(text.split())
        chars = len(text)
        return max(1, int(math.ceil(max(words * 1.3, chars / 4.0))))

    def message_rows(self, messages):
        rows = []
        for index, message in enumerate(messages or []):
            role = message.get("role") if isinstance(message, dict) else "text"
            text = self.message_text(message)
            rows.append({
                "index": index,
                "role": str(role or "unknown"),
                "tokens": self.token_estimate(text) + 4,
                "chars": len(text),
                "preview": " ".join(text.split())[:160],
            })
        return rows

    def max_output_tokens(self, data, model):
        raw = data.get("max_tokens") if isinstance(data, dict) else None
        if raw in (None, "") and isinstance(model, dict):
            raw = model.get("max_output_tokens")
        try:
            return max(1, int(raw or 512))
        except (TypeError, ValueError):
            return 512

    def context_window(self, model):
        for key in ("context_window", "context_length"):
            try:
                value = int((model or {}).get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return 0

    def model_ids(self, action, data):
        data = data if isinstance(data, dict) else {}
        if action in {"comparison", "compare"} and isinstance(data.get("models"), list):
            return [str(model) for model in data.get("models") if str(model or "").strip()][:5]
        if action in {"eval", "eval_run"} and isinstance(data.get("models"), list):
            return [str(model) for model in data.get("models") if str(model or "").strip()]
        model = str(data.get("model") or data.get("model_id") or "").strip()
        return [model or self.default_text_model()]

    def chat_messages(self, data):
        data = data if isinstance(data, dict) else {}
        messages = list(data.get("messages") if isinstance(data.get("messages"), list) else [])
        prompt = str(data.get("prompt") or "").strip()
        if prompt:
            messages.append({"role": "user", "content": prompt})
        return messages

    def missing_eval_dataset(self, dataset_id, exc):
        message = str(exc)
        expected = "Eval dataset '%s' was not found." % dataset_id
        return message == expected

    def eval_messages(self, data, warnings=None):
        data = data if isinstance(data, dict) else {}
        dataset_id = str(data.get("dataset_id") or "smoke")
        try:
            dataset = self.load_eval_dataset(dataset_id) or {}
        except ValueError as exc:
            if not self.missing_eval_dataset(dataset_id, exc):
                raise
            if warnings is not None:
                warnings.append({
                    "severity": "warning",
                    "code": "eval_dataset_unavailable",
                    "message": "Eval dataset is unavailable for context estimation.",
                    "dataset_id": dataset_id,
                })
            return [{"role": "eval_dataset_unavailable", "content": "eval dataset unavailable: %s" % dataset_id}]
        examples = dataset.get("examples") if isinstance(dataset.get("examples"), list) else []
        try:
            limit = max(1, int(data.get("max_examples") or len(examples) or 1))
        except (TypeError, ValueError):
            limit = len(examples) or 1
        rows = []
        for example in examples[:limit]:
            if not isinstance(example, dict):
                continue
            text = "\n".join(str(example.get(key) or "") for key in ("input", "expected", "context") if example.get(key))
            rows.append({"role": "eval_example", "content": text})
        return rows

    def code_messages(self, data):
        data = data if isinstance(data, dict) else {}
        parts = []
        for key, label in (
            ("print_prompt", "task"),
            ("project_dir", "project"),
            ("add_dirs", "additional directories"),
            ("allowed_tools", "allowed tools"),
            ("disallowed_tools", "disallowed tools"),
            ("extra_args", "extra args"),
        ):
            value = str(data.get(key) or "").strip()
            if value:
                parts.append("%s: %s" % (label, value))
        return [{"role": "code_launch", "content": "\n".join(parts) or "interactive Claude Code session"}]

    def action_messages(self, action, data, warnings=None):
        if action in {"eval", "eval_run"}:
            return self.eval_messages(data, warnings=warnings)
        if action in {"code", "tmux", "claude_code"}:
            return self.code_messages(data)
        return self.chat_messages(data)

    def warnings(self, model_id, model, input_tokens, output_tokens, context_window):
        warnings = []
        model_max_output = 0
        try:
            model_max_output = int((model or {}).get("max_output_tokens") or 0)
        except (TypeError, ValueError):
            model_max_output = 0
        if not model:
            warnings.append({"severity": "warning", "code": "unknown_model", "message": "Model metadata is not available.", "model": model_id})
        if context_window <= 0:
            warnings.append({"severity": "warning", "code": "missing_context_window", "message": "Model registry does not include a context window.", "model": model_id})
            return warnings
        if input_tokens > context_window:
            warnings.append({"severity": "error", "code": "context_exceeded", "message": "Estimated input exceeds the model context window.", "model": model_id})
        elif input_tokens + output_tokens > context_window:
            warnings.append({"severity": "error", "code": "output_exceeds_remaining_context", "message": "Requested output does not fit after estimated input tokens.", "model": model_id})
        elif input_tokens >= context_window * 0.9:
            warnings.append({"severity": "warning", "code": "truncation_risk", "message": "Estimated input uses at least 90% of the context window.", "model": model_id})
        if model_max_output and output_tokens > model_max_output:
            warnings.append({"severity": "warning", "code": "max_output_exceeds_model_limit", "message": "Requested output exceeds model max output metadata.", "model": model_id})
        return warnings

    def inspect(self, request):
        request = request if isinstance(request, dict) else {}
        action = str(request.get("action") or "chat").strip().lower()
        data = request.get("payload") if isinstance(request.get("payload"), dict) else request
        all_warnings = []
        messages = self.action_messages(action, data, warnings=all_warnings)
        rows = self.message_rows(messages)
        input_tokens = sum(row["tokens"] for row in rows)
        registry = self.models()
        results = []
        for model_id in self.model_ids(action, data):
            model = registry.get(str(model_id or "")) or {}
            context_window = self.context_window(model)
            output_tokens = self.max_output_tokens(data, model)
            remaining = None if context_window <= 0 else max(0, context_window - input_tokens - output_tokens)
            warnings = self.warnings(model_id, model, input_tokens, output_tokens, context_window)
            all_warnings.extend(warnings)
            results.append({
                "model": model_id,
                "display_name": model.get("display_name") or model_id,
                "context_window": context_window,
                "max_output_tokens": output_tokens,
                "model_max_output_tokens": model.get("max_output_tokens"),
                "input_tokens_est": input_tokens,
                "total_tokens_est": input_tokens + output_tokens,
                "remaining_context_tokens": remaining,
                "fits": context_window <= 0 or (input_tokens + output_tokens) <= context_window,
                "warnings": warnings,
            })
        return {
            "action": action,
            "generated_at": self.clock(),
            "approximate": True,
            "input_tokens_est": input_tokens,
            "message_count": len(rows),
            "messages": rows,
            "models": results,
            "warnings": all_warnings,
            "assumptions": [
                "Token counts are approximate and use local text heuristics.",
                "Provider tokenizers, hidden system prompts, tools, files, and retrieval context can change actual counts.",
                "Eval estimates show the selected example window rather than exact provider batching behavior.",
            ],
        }
