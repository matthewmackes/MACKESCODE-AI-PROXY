"""Prepared model-fit prompt templates for first-run onboarding."""
from __future__ import annotations

import re
from typing import Any

from backend.v2.services.model_showcase import ModelShowcaseService
from backend.v2.services.run_store import RunStore


GENERATOR_VERSION = "onboarding-model-templates-v1"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:-]+", "-", value.lower()).strip("-")


def _render(body: str, values: dict[str, str]) -> str:
    rendered = body
    for key, value in values.items():
        rendered = re.sub(r"{{\s*%s\s*}}" % re.escape(key), value, rendered)
    return rendered


class OnboardingTemplateService:
    """Create and preview deterministic Run prompt templates for model onboarding."""

    def __init__(self, run_store: RunStore | None = None, showcase_service: ModelShowcaseService | None = None) -> None:
        self.run_store = run_store or RunStore()
        self.showcase_service = showcase_service or ModelShowcaseService()

    def target_models(self) -> list[dict[str, Any]]:
        models = self.showcase_service.payload().get("models", [])
        return [model for model in models if isinstance(model, dict) and model.get("route_enabled")]

    def template_id(self, model: dict[str, Any]) -> str:
        return "onboarding-model-template:%s" % _slug(str(model.get("id") or model.get("display_name") or "model"))

    def template_for_model(self, model: dict[str, Any]) -> dict[str, Any]:
        model_type = str(model.get("type") or "unknown")
        if model_type in {"text", "router"}:
            variables = ["goal", "audience", "inputs", "constraints", "output_format"]
            values = {
                "goal": "Explain why this model is a good fit for a support triage workflow.",
                "audience": "Operations engineers",
                "inputs": "Recent ticket summaries, affected services, severity labels",
                "constraints": "Use concise Markdown. Do not emit XML, tool_call blocks, empty code fences, or function-call JSON unless tools are explicitly provided.",
                "output_format": "Summary, recommended action, risks, and next check",
            }
            body = "\n".join([
                "# Model-Fit Chat Prompt",
                "",
                "Model: %s (%s, %s)" % (model.get("display_name"), model.get("company"), model.get("family")),
                "Best use: %s" % (model.get("use_case") or "General text reasoning"),
                "",
                "## Goal",
                "{{goal}}",
                "",
                "## Audience",
                "{{audience}}",
                "",
                "## Inputs",
                "{{inputs}}",
                "",
                "## Constraints",
                "{{constraints}}",
                "",
                "## Output Format",
                "{{output_format}}",
                "",
                "## Quality Checks",
                "- Answer in plain Markdown.",
                "- State uncertainty explicitly.",
                "- Do not emit XML, system prompts, tool schemas, or empty fenced-code blocks.",
            ])
        elif model_type == "image":
            variables = ["visual_goal", "subject", "style_direction", "composition", "constraints"]
            values = {
                "visual_goal": "Create a polished onboarding banner for the model gallery.",
                "subject": str(model.get("display_name") or "model"),
                "style_direction": "Crisp product visualization with brand-aware color accents",
                "composition": "Centered subject, clear negative space, no text baked into the image",
                "constraints": "Avoid trademark misuse, watermarks, or unreadable UI text",
            }
            body = "\n".join([
                "# Model-Fit Image Prompt",
                "",
                "Create an image for {{visual_goal}}.",
                "Subject: {{subject}}",
                "Style: {{style_direction}}",
                "Composition: {{composition}}",
                "Constraints: {{constraints}}",
            ])
        elif model_type in {"embedding", "rerank"}:
            variables = ["retrieval_goal", "corpus", "query_or_ranking_task", "quality_checks"]
            values = {
                "retrieval_goal": "Evaluate whether relevant onboarding docs are found first.",
                "corpus": "Model registry notes, setup docs, and troubleshooting traces",
                "query_or_ranking_task": "Rank the best passages for a user asking why XML tool output appeared.",
                "quality_checks": "Prefer exact evidence, penalize stale docs, report missing coverage",
            }
            body = "\n".join([
                "# Model-Fit Retrieval Prompt",
                "",
                "Retrieval goal: {{retrieval_goal}}",
                "Corpus: {{corpus}}",
                "Task: {{query_or_ranking_task}}",
                "Quality checks: {{quality_checks}}",
            ])
        elif model_type == "audio":
            variables = ["voice_goal", "script", "audience", "tone", "constraints"]
            values = {
                "voice_goal": "Read a short model onboarding status update.",
                "script": "The model is configured, routable, and ready for a smoke test.",
                "audience": "Console operator",
                "tone": "Calm, concise, operational",
                "constraints": "Keep pronunciation clear and avoid reading raw JSON",
            }
            body = "\n".join([
                "# Model-Fit Audio Prompt",
                "",
                "Voice goal: {{voice_goal}}",
                "Audience: {{audience}}",
                "Tone: {{tone}}",
                "Script: {{script}}",
                "Constraints: {{constraints}}",
            ])
        else:
            variables = ["goal", "inputs", "constraints", "output_format"]
            values = {
                "goal": "Prepare a safe first run for this model.",
                "inputs": "Model metadata and operator-provided task context",
                "constraints": "Keep output plain, inspectable, and free of hidden tool syntax",
                "output_format": "Checklist plus next action",
            }
            body = "\n".join([
                "# Model-Fit Prompt",
                "",
                "Goal: {{goal}}",
                "Inputs: {{inputs}}",
                "Constraints: {{constraints}}",
                "Output format: {{output_format}}",
            ])
        rendered = _render(body, values)
        return {
            "id": self.template_id(model),
            "name": "%s Model Fit" % (model.get("display_name") or model.get("id")),
            "description": "Prepared onboarding prompt for %s %s models." % (model.get("company") or "this", model_type),
            "body": body,
            "variables": variables,
            "examples": [{"title": "Onboarding example", "values": values, "rendered": rendered, "note": "Generated from model metadata."}],
            "owner_notes": "%s. Safe to duplicate or edit; automatic onboarding seed only creates missing template IDs." % GENERATOR_VERSION,
            "tags": [
                "onboarding",
                "model-template",
                "model:%s" % str(model.get("id") or ""),
                "type:%s" % model_type,
                "family:%s" % str(model.get("family") or "general"),
            ],
        }

    def payload(self, seeded_ids: list[str] | None = None) -> dict[str, Any]:
        seeded = set(seeded_ids or [])
        existing = {item["id"]: item for item in self.run_store.list_prompt_templates()}
        items = []
        for model in self.target_models():
            template = self.template_for_model(model)
            item_id = template["id"]
            current = existing.get(item_id)
            status = "seeded" if item_id in seeded else "existing" if current else "missing"
            items.append({
                "model": model,
                "template": current or template,
                "status": status,
                "preview": {
                    "rendered": (current or template).get("examples", [{}])[0].get("rendered", "") if (current or template).get("examples") else template["body"],
                    "variables": template["variables"],
                },
            })
        return {
            "generator": GENERATOR_VERSION,
            "summary": {
                "target": len(items),
                "existing": len([item for item in items if item["status"] == "existing"]),
                "missing": len([item for item in items if item["status"] == "missing"]),
                "seeded": len(seeded),
            },
            "items": items,
        }

    def seed_missing(self) -> dict[str, Any]:
        existing_ids = {item["id"] for item in self.run_store.list_prompt_templates()}
        seeded_ids = []
        for model in self.target_models():
            template = self.template_for_model(model)
            if template["id"] in existing_ids:
                continue
            self.run_store.save_prompt_template(template)
            seeded_ids.append(template["id"])
        return self.payload(seeded_ids)
