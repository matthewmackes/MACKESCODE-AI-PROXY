"""Detailed model hero-card payloads derived from the global registry."""
import json


class ModelHeroService:
    """Build rich per-model descriptions without creating a second model registry."""

    def __init__(self, descriptions_dir):
        self.descriptions_dir = descriptions_dir

    def load_family_profiles(self):
        path = self.descriptions_dir / "families.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        families = data.get("families") if isinstance(data, dict) else {}
        return families if isinstance(families, dict) else {}

    def profile_for(self, option, profiles):
        family = str((option or {}).get("family") or "general").strip().lower()
        brand = str((option or {}).get("brand") or "").strip().lower()
        model_id = str((option or {}).get("id") or "").strip().lower()
        for key in (family, brand, model_id):
            if key in profiles:
                return profiles[key], key
        for key, profile in profiles.items():
            if key and (key in family or key in brand or key in model_id):
                return profile, key
        return profiles.get("general", {}), "general"

    def access_label(self, option):
        if (option or {}).get("disabled"):
            return (option or {}).get("status") or "Unavailable"
        return (option or {}).get("status") or "Available"

    def deployment_label(self, option):
        dedicated = (option or {}).get("dedicated") if isinstance((option or {}).get("dedicated"), dict) else {}
        if dedicated.get("managed"):
            state = dedicated.get("state") or "configured"
            return "Dedicated Inference (%s)" % state
        if (option or {}).get("serverless"):
            return "Serverless Inference"
        return "Global registry"

    def model_summary(self, option, profile):
        name = (option or {}).get("display_name") or (option or {}).get("id") or "This model"
        family = (option or {}).get("family") or "General"
        base = profile.get("summary") or "%s is available through the global model registry." % family
        return "%s is a %s-family option. %s" % (name, family, base)

    def score_alternative(self, option, candidate):
        if not candidate or candidate.get("id") == option.get("id"):
            return -1
        score = 0
        if candidate.get("type") == option.get("type"):
            score += 5
        if candidate.get("family") == option.get("family"):
            score += 2
        if not candidate.get("disabled"):
            score += 1
        return score

    def alternatives_for(self, option, options, profile):
        named = [str(item) for item in profile.get("alternatives", []) if item]
        candidates = []
        for candidate in options:
            score = self.score_alternative(option, candidate)
            haystack = " ".join(str(candidate.get(k) or "") for k in ("id", "display_name", "family", "brand")).lower()
            if any(name.lower() in haystack for name in named):
                score += 4
            if score > 0:
                candidates.append((score, candidate))
        candidates.sort(key=lambda item: (-item[0], str(item[1].get("display_name") or item[1].get("id") or "")))
        return [
            {
                "id": candidate.get("id"),
                "display_name": candidate.get("display_name") or candidate.get("id"),
                "family": candidate.get("family") or "General",
                "cost_label": candidate.get("cost_label") or "Pricing unavailable",
                "access_state": self.access_label(candidate),
            }
            for _, candidate in candidates[:4]
        ]

    def hero_card(self, option, all_options=None, profiles=None):
        option = dict(option or {})
        all_options = list(all_options or [option])
        profiles = profiles or self.load_family_profiles()
        profile, profile_key = self.profile_for(option, profiles)
        strengths = list(profile.get("strengths") or [])
        weaknesses = list(profile.get("weaknesses") or [])
        best_for = list(profile.get("best_for") or [])
        use_case = option.get("use_case") or ""
        if use_case and use_case not in best_for:
            best_for = [use_case] + best_for
        return {
            "id": option.get("id") or "",
            "display_name": option.get("display_name") or option.get("id") or "",
            "summary": self.model_summary(option, profile),
            "type": option.get("type") or "text",
            "brand": option.get("brand") or "DigitalOcean",
            "family": option.get("family") or "General",
            "origin": option.get("origin") or "Unknown",
            "logo_url": option.get("logo_url") or "",
            "cost_label": option.get("cost_label") or "Pricing unavailable",
            "access_state": self.access_label(option),
            "deployment": self.deployment_label(option),
            "best_for": best_for[:5],
            "strengths": strengths[:5],
            "weaknesses": weaknesses[:5],
            "alternatives": self.alternatives_for(option, all_options, profile),
            "comparison": option.get("comparison") or option.get("use_case") or "",
            "context_window": option.get("context_window") or 0,
            "pricing": dict(option.get("pricing") or {}),
            "style": dict(option.get("style") or {}),
            "is_new": bool(option.get("is_new")),
            "new_until": option.get("new_until") or 0,
            "description_source": "config/model-descriptions/families.json:%s + global model registry" % profile_key,
        }

    def hero_cards(self, options):
        options = [dict(option or {}) for option in options if (option or {}).get("id")]
        profiles = self.load_family_profiles()
        cards = [self.hero_card(option, options, profiles) for option in options]
        return {"models": cards, "model_info": {card["id"]: card for card in cards}}
