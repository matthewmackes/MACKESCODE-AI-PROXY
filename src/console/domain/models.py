"""Model registry domain records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_1m: float = 0.0
    output_usd_per_1m: float = 0.0

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        return cls(float(data.get("input_usd_per_1m") or data.get("input") or 0.0), float(data.get("output_usd_per_1m") or data.get("output") or 0.0))

    def to_dict(self):
        return {"input_usd_per_1m": self.input_usd_per_1m, "output_usd_per_1m": self.output_usd_per_1m}


@dataclass(frozen=True)
class ModelRecord:
    id: str
    display_name: str = ""
    type: str = "text"
    enabled: bool = True
    pricing: ModelPricing = field(default_factory=ModelPricing)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        model_id = str(data.get("id") or data.get("model") or "").strip()
        if not model_id:
            raise ValueError("model id is required")
        known = {"id", "model", "display_name", "name", "type", "enabled", "pricing"}
        return cls(model_id, str(data.get("display_name") or data.get("name") or model_id), str(data.get("type") or "text"), bool(data.get("enabled", True)), ModelPricing.from_dict(data.get("pricing")), {key: value for key, value in data.items() if key not in known})

    def to_dict(self):
        row = dict(self.extra)
        row.update({"id": self.id, "display_name": self.display_name, "type": self.type, "enabled": self.enabled, "pricing": self.pricing.to_dict()})
        return row
