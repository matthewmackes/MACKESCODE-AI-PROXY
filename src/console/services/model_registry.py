"""Model registry normalization, routing policy, and selector metadata."""
import json


DEFAULT_BRAND_PROFILES = [
    ("anthropic", {"brand": "Anthropic", "origin": "United States", "logo": "https://cdn.simpleicons.org/anthropic/000000", "family": "Claude"}),
    ("openai", {"brand": "OpenAI", "origin": "United States", "logo": "https://cdn.simpleicons.org/openai/000000", "family": "GPT"}),
    ("deepseek", {"brand": "DeepSeek", "origin": "China", "logo": "https://cdn.simpleicons.org/deepseek/4D6BFE", "family": "DeepSeek"}),
    ("mistral", {"brand": "Mistral AI", "origin": "France", "logo": "https://cdn.simpleicons.org/mistralai/FA520F", "family": "Mistral"}),
    ("qwen", {"brand": "Alibaba Qwen", "origin": "China", "logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "family": "Qwen"}),
    ("alibaba", {"brand": "Alibaba Qwen", "origin": "China", "logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "family": "Qwen"}),
    ("glm", {"brand": "Zhipu AI", "origin": "China", "logo": "", "family": "GLM"}),
    ("kimi", {"brand": "Moonshot AI", "origin": "China", "logo": "", "family": "Kimi"}),
    ("llama", {"brand": "Meta", "origin": "United States", "logo": "https://cdn.simpleicons.org/meta/0467DF", "family": "Llama"}),
    ("gemma", {"brand": "Google", "origin": "United States", "logo": "https://cdn.simpleicons.org/google/4285F4", "family": "Gemma"}),
    ("nemotron", {"brand": "NVIDIA", "origin": "United States", "logo": "https://cdn.simpleicons.org/nvidia/76B900", "family": "Nemotron"}),
    ("nvidia", {"brand": "NVIDIA", "origin": "United States", "logo": "https://cdn.simpleicons.org/nvidia/76B900", "family": "Nemotron"}),
    ("minimax", {"brand": "MiniMax", "origin": "China", "logo": "", "family": "MiniMax"}),
    ("mimo", {"brand": "Xiaomi", "origin": "China", "logo": "https://cdn.simpleicons.org/xiaomi/FF6900", "family": "MiMo"}),
    ("arcee", {"brand": "Arcee AI", "origin": "United States", "logo": "", "family": "Arcee"}),
    ("stable-diffusion", {"brand": "Stability AI", "origin": "United Kingdom", "logo": "https://cdn.simpleicons.org/stabilityai/000000", "family": "Stable Diffusion"}),
    ("flux", {"brand": "Black Forest Labs", "origin": "Germany", "logo": "", "family": "FLUX"}),
    ("bge", {"brand": "BAAI", "origin": "China", "logo": "", "family": "BGE"}),
    ("e5", {"brand": "Microsoft", "origin": "United States", "logo": "https://cdn.simpleicons.org/microsoft/5E5E5E", "family": "E5"}),
    ("gte", {"brand": "Alibaba", "origin": "China", "logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "family": "GTE"}),
]


class ModelRegistryService:
    """Owns model registry policy, persistence, and enriched selector metadata."""

    def __init__(self, default_registry, model_types, auto_enable_max_usd, brand_profiles=None):
        self.default_registry = list(default_registry)
        self.model_types = set(model_types)
        self.auto_enable_max_usd = float(auto_enable_max_usd)
        self.brand_profiles = list(brand_profiles or DEFAULT_BRAND_PROFILES)

    def enabled_by_default(self, pricing):
        prices = []
        for key in ("input", "output", "image"):
            if key in pricing:
                try:
                    price = float(pricing.get(key) or 0)
                    if price > 0:
                        prices.append(price)
                except (TypeError, ValueError):
                    return False
        return bool(prices) and all(price < self.auto_enable_max_usd for price in prices)

    def route_enabled(self, model):
        if not model.get("enabled"):
            return False
        if model.get("serverless") and model.get("type") == "text":
            return model.get("access_status") == "ok"
        return True

    def normalize(self, item):
        if not isinstance(item, dict):
            return None
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            return None
        model_type = str(item.get("type") or "text").strip().lower()
        if model_type not in self.model_types:
            model_type = "unknown"
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        raw_pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        pricing = {key: float(value or 0) for key, value in raw_pricing.items() if key in ("input", "output", "image", "hourly")}
        enabled = bool(item["enabled"]) if "enabled" in item else self.enabled_by_default(pricing)
        normalized = {
            "id": model_id,
            "display_name": str(item.get("display_name") or model_id),
            "type": model_type,
            "provider": str(item.get("provider") or "DigitalOcean"),
            "enabled": enabled,
            "aliases": [str(alias).strip() for alias in aliases if str(alias).strip()],
            "pricing": pricing,
            "context_window": int(item.get("context_window") or 0),
        }
        if isinstance(item.get("dedicated"), dict):
            normalized["dedicated"] = item["dedicated"]
        for key in ("state", "inference_id", "serverless", "owned_by", "created", "max_output_tokens", "pricing_source", "auto_managed", "access_status", "last_error"):
            if item.get(key):
                normalized[key] = item[key]
        return normalized

    def load(self, path, include_disabled=True):
        models = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                models = data.get("models") if isinstance(data, dict) else data
            except (OSError, ValueError):
                models = None
        if not isinstance(models, list):
            models = self.default_registry
        normalized = [item for item in (self.normalize(model) for model in models) if item]
        if not normalized:
            normalized = [self.normalize(model) for model in self.default_registry]
        return normalized if include_disabled else [model for model in normalized if self.route_enabled(model)]

    def save(self, path, models):
        normalized = [item for item in (self.normalize(model) for model in models) if item]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"models": normalized}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return normalized

    def serverless_model_type(self, model_id):
        lower = str(model_id or "").lower()
        if lower.startswith("router:"):
            return "router"
        if "rerank" in lower:
            return "rerank"
        if "embedding" in lower or lower in {"all-mini-lm-l6-v2", "bge-m3", "e5-large-v2", "gte-large-en-v1.5", "multi-qa-mpnet-base-dot-v1"}:
            return "embedding"
        if "tts" in lower or "audio" in lower:
            return "audio"
        if "t2v" in lower or "video" in lower or lower.startswith("wan"):
            return "video"
        if "image" in lower or "stable-diffusion" in lower or "flux" in lower or "sdxl" in lower:
            return "image"
        return "text"

    def display_name_from_model_id(self, model_id):
        text = str(model_id or "").replace("router:", "router ").replace("/", " ").replace("-", " ").replace("_", " ")
        return " ".join(part.upper() if part.lower() in {"ai", "vl", "tts", "bge", "glm"} else part[:1].upper() + part[1:] for part in text.split())

    def catalog_price_value(self, item, keys):
        for key in keys:
            if key in item:
                try:
                    value = float(item.get(key) or 0)
                    if value > 0:
                        return value
                except (TypeError, ValueError):
                    continue
        return 0.0

    def catalog_pricing_from_item(self, item):
        if not isinstance(item, dict):
            return {}
        sources = []
        for key in ("pricing", "prices", "rates", "cost", "costs"):
            value = item.get(key)
            if isinstance(value, dict):
                sources.append(value)
        sources.append(item)
        pricing = {}
        for source in sources:
            input_price = self.catalog_price_value(source, ("input", "input_usd_per_million", "input_price", "prompt", "prompt_usd_per_million", "prompt_price"))
            output_price = self.catalog_price_value(source, ("output", "output_usd_per_million", "output_price", "completion", "completion_usd_per_million", "completion_price"))
            image_price = self.catalog_price_value(source, ("image", "image_usd", "image_price", "price_per_image"))
            if input_price:
                pricing["input"] = input_price
            if output_price:
                pricing["output"] = output_price
            if image_price:
                pricing["image"] = image_price
            if pricing:
                break
        return pricing

    def brand_profile(self, model):
        model_id = str((model or {}).get("id") or "").lower()
        owned_by = str((model or {}).get("owned_by") or "").lower()
        haystack = model_id + " " + owned_by
        for needle, profile in self.brand_profiles:
            if needle in haystack:
                return dict(profile)
        return {"brand": (model or {}).get("owned_by") or (model or {}).get("provider") or "DigitalOcean", "origin": "Unknown", "logo": "", "family": "General"}

    def readable_cost(self, model):
        pricing = (model or {}).get("pricing") if isinstance((model or {}).get("pricing"), dict) else {}
        parts = []
        if float(pricing.get("input") or 0) > 0:
            parts.append("$%.3g input / 1M tokens" % float(pricing.get("input")))
        if float(pricing.get("output") or 0) > 0:
            parts.append("$%.3g output / 1M tokens" % float(pricing.get("output")))
        if float(pricing.get("image") or 0) > 0:
            parts.append("$%.3g / image" % float(pricing.get("image")))
        if float(pricing.get("hourly") or 0) > 0:
            parts.append("$%.2f / hour" % float(pricing.get("hourly")))
        return " ; ".join(parts) if parts else "Pricing unavailable"

    def use_case(self, model, profile):
        model_id = str((model or {}).get("id") or "").lower()
        model_type = str((model or {}).get("type") or "text")
        if model_type == "image":
            return "Image generation and visual ideation; compare against other image models when prompt fidelity or style range matters."
        if model_type in {"embedding", "rerank"}:
            return "Search, retrieval, and ranking infrastructure; compare by vector quality, latency, and index cost rather than chat quality."
        if "coder" in model_id or "codex" in model_id:
            return "Strong fit for coding and agentic tool use; compare with DeepSeek and Qwen models when cost matters."
        if "flash" in model_id or "nano" in model_id or "mimo" in model_id:
            return "Fast, economical everyday work; compare with Mistral or smaller DeepSeek models for latency-sensitive tasks."
        if "r1" in model_id or "thinking" in model_id:
            return "Reasoning-heavy analysis and multi-step problem solving; compare with larger Qwen, GLM, and DeepSeek models."
        if "qwen" in model_id:
            return "Broad multilingual coding and reasoning; compare with DeepSeek for coding and GLM/Kimi for long-form analysis."
        if "deepseek" in model_id:
            return "Practical coding, reasoning, and low-cost automation; compare with Qwen for multilingual work."
        if "glm" in model_id or "kimi" in model_id:
            return "Long-context writing, analysis, and general assistant work; compare with Qwen and Llama for breadth."
        if "llama" in model_id or "gemma" in model_id:
            return "General open-model chat and summarization; compare with Mistral for concise answers and Qwen for coding."
        if "nemotron" in model_id or "nvidia" in model_id:
            return "Enterprise-style instruction following and structured outputs; compare with Llama and OpenAI OSS models."
        if "anthropic" in model_id:
            return "Claude-style writing and careful reasoning when available; compare with OpenAI and Mistral for general chat."
        if "openai" in model_id:
            return "General assistant, coding, and structured output workloads when available; compare with Claude and DeepSeek families."
        if "mistral" in model_id:
            return "Concise general chat, summarization, and fast drafting; compare with DeepSeek and Llama for cost and tone."
        return "%s-family general assistant model; compare with similarly priced models for latency, context, and output style." % profile.get("family", "General")

    def status_label(self, model):
        if self.route_enabled(model):
            return "Available"
        access = (model or {}).get("access_status") or "not_checked"
        if access == "forbidden":
            return "Unavailable for this key"
        if access == "rate_limited":
            return "Temporarily rate limited"
        if access == "probe_failed":
            return "Probe failed"
        if (model or {}).get("enabled") is False:
            return "Disabled"
        return "Needs key audit"

    def enriched_option(self, model):
        profile = self.brand_profile(model)
        disabled = not self.route_enabled(model)
        name = str((model or {}).get("display_name") or (model or {}).get("id") or "")
        cost = self.readable_cost(model)
        status = self.status_label(model)
        label = "%s - %s - Training origin: %s - %s" % (name, profile["brand"], profile["origin"], cost)
        if disabled:
            label += " - " + status
        use_case = self.use_case(model, profile)
        return {
            "id": (model or {}).get("id") or "",
            "label": label,
            "display_name": name,
            "type": (model or {}).get("type") or "text",
            "brand": profile["brand"],
            "family": profile["family"],
            "origin": profile["origin"],
            "logo_url": profile["logo"],
            "cost_label": cost,
            "status": status,
            "disabled": disabled,
            "enabled": bool((model or {}).get("enabled")),
            "access_status": (model or {}).get("access_status") or "not_checked",
            "use_case": use_case,
            "comparison": use_case,
        }

    def options(self, rows, model_type=None, include_disabled=True):
        if model_type:
            rows = [model for model in rows if model.get("type") == model_type]
        if not include_disabled:
            rows = [model for model in rows if self.route_enabled(model)]
        return [self.enriched_option(model) for model in rows]

    def metadata_map(self, options):
        return {item["id"]: item for item in options}
