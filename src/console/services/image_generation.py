"""Image prompt construction and generation orchestration."""
import time
import uuid
from http import HTTPStatus


class ImageGenerationService:
    """Owns image request validation, prompt building, and history records."""

    def __init__(
        self,
        styles,
        sizes,
        image_models,
        image_cost_usd,
        default_image_model,
        start_proxy_if_needed,
        request_json,
        proxy_url,
        save_image_item,
        append_history,
        clock=None,
        uuid_factory=None,
    ):
        self.styles = styles
        self.sizes = list(sizes)
        self.image_models = image_models
        self.image_cost_usd = image_cost_usd
        self.default_image_model = default_image_model
        self.start_proxy_if_needed = start_proxy_if_needed
        self.request_json = request_json
        self.proxy_url = proxy_url
        self.save_image_item = save_image_item
        self.append_history = append_history
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def active_image_models(self):
        return list(self.image_models() if callable(self.image_models) else self.image_models)

    def image_costs(self):
        return dict(self.image_cost_usd() if callable(self.image_cost_usd) else self.image_cost_usd)

    def build_prompt(self, data):
        prompt = (data.get("prompt") or "").strip()
        builder = data.get("builder") if isinstance(data.get("builder"), dict) else {}
        parts = []
        for key in ("subject", "environment", "lighting", "camera", "mood", "materials", "palette"):
            value = (builder.get(key) or "").strip()
            if value:
                parts.append(value)
        if parts:
            prompt = ", ".join([prompt] + parts) if prompt else ", ".join(parts)
        style = data.get("style") or "none"
        if self.styles.get(style):
            prompt = prompt + ", " + self.styles[style] if prompt else self.styles[style]
        negative = (data.get("negative_prompt") or "").strip()
        if negative:
            prompt += ". Avoid: " + negative
        source_prompt = (data.get("source_prompt") or "").strip()
        iteration = (data.get("iteration") or "").strip()
        if source_prompt and iteration:
            prompt = "%s. Revise with: %s" % (source_prompt, iteration)
        return prompt.strip()

    def generate(self, data):
        self.start_proxy_if_needed()
        model = data.get("model") or self.default_image_model()
        if model not in self.active_image_models():
            return HTTPStatus.BAD_REQUEST, {"error": "unknown image model"}
        prompt = self.build_prompt(data)
        if not prompt:
            return HTTPStatus.BAD_REQUEST, {"error": "prompt is required"}
        try:
            count = max(1, min(4, int(data.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1
        size = data.get("size") if data.get("size") in self.sizes else "1024x1024"
        payload = {"model": model, "prompt": prompt, "size": size, "n": count}
        if str(data.get("seed") or "").strip():
            payload["seed"] = str(data["seed"]).strip()
        status, response = self.request_json(self.proxy_url("/v1/images/generations"), payload)
        if status >= 400:
            return status, response
        records = []
        costs = self.image_costs()
        for item in response.get("data") or []:
            image_id = self.uuid_factory().hex
            path = self.save_image_item(item, image_id)
            record = {
                "id": image_id,
                "created_at": self.clock(),
                "model": model,
                "prompt": prompt,
                "negative_prompt": data.get("negative_prompt") or "",
                "style": data.get("style") or "none",
                "size": size,
                "seed": data.get("seed") or "",
                "cost_usd": costs.get(model, 0.0),
                "filename": path.name,
            }
            self.append_history(record)
            records.append(record)
        return HTTPStatus.OK, {"images": records}
