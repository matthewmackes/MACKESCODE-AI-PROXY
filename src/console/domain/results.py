"""Shared result domain records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ErrorInfo:
    message: str
    code: str = ""
    category: str = ""
    details: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        message = str(data.get("message") or data.get("error") or "").strip()
        if not message:
            raise ValueError("error message is required")
        return cls(message, str(data.get("code") or ""), str(data.get("category") or ""), data.get("details") if isinstance(data.get("details"), dict) else {})

    def to_dict(self):
        return {"message": self.message, "code": self.code, "category": self.category, "details": self.details}
