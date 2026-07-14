import json
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.performance_analyst import PerformanceAnalystService
from src.console.services.operational_store import OperationalStore


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class FakeLegacyAdapter:
    def __init__(self, success_rate=0.99, latency_ms=800, chat_payload=None):
        self.success_rate = success_rate
        self.latency_ms = latency_ms
        self.chat_payload = chat_payload
        self.chat_calls = 0
        self.automation_events = []

    def _safe_call(self, name, fallback, **kwargs):
        if name == "analytics_payload":
            return {"summary": {"success_rate": self.success_rate, "avg_latency_ms": self.latency_ms}}
        if name == "model_scorecards_payload":
            return {"models": []}
        return fallback

    def observe_payload(self, days=7, trace_limit=200, audit_limit=80):
        return {
            "cost": {"digitalocean": {"local_estimate_cross_check": {"status": "aligned"}}},
            "provider_health": {"findings": []},
            "telemetry": {},
            "evals": {},
        }

    def operate_payload(self):
        return {
            "release_candidate": {"summary": {"status": "ready"}},
            "config_drift": {"summary": {"active_drift_count": 0}},
            "cost_control": {"paused": False},
        }

    def chat_completion(self, payload):
        self.chat_calls += 1
        if self.chat_payload is None:
            return 500, {"error": "disabled"}
        return 200, self.chat_payload

    def run_automation_event(self, payload):
        self.automation_events.append(payload)
        return {"ok": True}


class FakeShowcase:
    def __init__(self, models):
        self.models = models

    def payload(self):
        return {"models": self.models}


def model_card(model_id, grade="A", input_price=0.1, output_price=0.2, route_enabled=True):
    return {
        "id": model_id,
        "display_name": model_id,
        "type": "text",
        "route_enabled": route_enabled,
        "pricing": {"input": input_price, "output": output_price},
        "health": {"grade": grade, "measured": True, "requests": 12, "success_rate": 0.99, "p50_latency_ms": 700},
    }


class PerformanceAnalystServiceTests(unittest.TestCase):
    def service(self, tmp, *, models=None, legacy=None, env=None, clock=None):
        return PerformanceAnalystService(
            legacy_adapter=legacy or FakeLegacyAdapter(),
            showcase_service=FakeShowcase(models or [model_card("grade-a-cheap", "A", 0.03, 0.05)]),
            store=OperationalStore(Path(tmp) / "ops.sqlite3", clock=clock or (lambda: 1000)),
            clock=clock or (lambda: 1000),
            env={
                "MATTS_ANALYST_PUBLIC_SWEEP": "0",
                "MATTS_ANALYST_LLM_ENABLED": "0",
                **(env or {}),
            },
        )

    def test_selects_cheapest_route_enabled_grade_a_text_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, models=[
                model_card("grade-b-cheap", "B", 0.01, 0.02),
                model_card("grade-a-expensive", "A", 0.2, 0.3),
                model_card("grade-a-cheap", "A", 0.03, 0.04),
                {**model_card("disabled", "A", 0.001, 0.001), "route_enabled": False},
            ])

            selected = service.select_analyst_model(service.telemetry_payload()["models"])

        self.assertEqual(selected["id"], "grade-a-cheap")
        self.assertEqual(selected["grade"], "A")
        self.assertFalse(selected["fallback"])

    def test_falls_back_to_best_available_non_a_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, models=[
                model_card("grade-c", "C", 0.01, 0.02),
                model_card("grade-b", "B", 0.03, 0.04),
            ])

            selected = service.select_analyst_model(service.telemetry_payload()["models"])

        self.assertEqual(selected["id"], "grade-b")
        self.assertTrue(selected["fallback"])

    def test_payload_skips_run_when_fingerprint_is_unchanged(self):
        clock = MutableClock(1000)
        legacy = FakeLegacyAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, legacy=legacy, clock=clock)
            first = service.payload(force=True, actor={"id": "operator"})
            second = service.payload(force=False, actor={"id": "operator"})

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["cache"]["status"], "hit")
        self.assertEqual(second["fingerprint"], first["fingerprint"])

    def test_plain_get_without_persisted_run_returns_preview_without_llm_call(self):
        legacy = FakeLegacyAdapter(chat_payload={"content": [{"text": "{}"}]})
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, legacy=legacy, env={"MATTS_ANALYST_LLM_ENABLED": "1"})
            payload = service.payload(force=False, actor={"id": "viewer"})

        self.assertEqual(payload["status"], "pending_full_analysis")
        self.assertEqual(payload["cache"]["status"], "preview")
        self.assertEqual(legacy.chat_calls, 0)
        self.assertIsNone(service.store.latest_analyst_run())

    def test_daily_cap_pauses_cost_bearing_assessment(self):
        clock = MutableClock(1000)
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, clock=clock, env={"MATTS_ANALYST_DAILY_CAP_USD": "0.01"})
            service.store.save_analyst_run({
                "run_id": "spent",
                "generated_at": 900,
                "status": "ok",
                "fingerprint": "old",
                "estimated_cost_usd": 0.02,
                "proxy": {"grade": "A"},
                "summary": {"severity_counts": {"high": 0, "medium": 0, "low": 0}},
                "findings": [],
            })

            payload = service.payload(force=True, actor={"id": "operator"})

        self.assertEqual(payload["status"], "paused_by_analyst_cap")
        self.assertEqual(payload["cap"]["status"], "exceeded")

    def test_deterministic_high_finding_pushes_external_event(self):
        legacy = FakeLegacyAdapter(success_rate=0.90)
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, legacy=legacy)
            payload = service.payload(force=True, actor={"id": "operator"})

        self.assertEqual(payload["summary"]["severity_counts"]["high"], 1)
        self.assertEqual(legacy.automation_events[0]["type"], "analyst.high")

    def test_strict_json_llm_payload_is_normalized(self):
        llm_doc = {
            "proxy": {"grade": "B", "score": 82, "narrative": "Stable with one warning."},
            "models": [{"model": "grade-a-cheap", "grade": "B", "score": 80, "narrative": "Measured."}],
            "findings": [{"severity": "medium", "title": "Latency warning", "metric": "p50", "value": 1200, "source": "models.health", "suggested_action": "Watch routing."}],
        }
        legacy = FakeLegacyAdapter(chat_payload={"content": [{"text": "```json\n%s\n```" % json.dumps(llm_doc)}]})
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, legacy=legacy, env={"MATTS_ANALYST_LLM_ENABLED": "1"})
            payload = service.payload(force=True, actor={"id": "operator"})

        self.assertEqual(payload["mode"], "llm")
        self.assertEqual(payload["proxy"]["grade"], "B")
        self.assertEqual(payload["findings"][0]["title"], "Latency warning")
        self.assertEqual(legacy.chat_calls, 1)


if __name__ == "__main__":
    unittest.main()
