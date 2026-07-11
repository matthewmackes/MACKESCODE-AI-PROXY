import tempfile
import unittest
from pathlib import Path

from src.console.services.cost_anomalies import CostAnomalyService


class CostAnomalyServiceTests(unittest.TestCase):
    def service(self, root, *, traces=None, evals=None, reviews=None, audits=None, dedicated=None, now=None):
        traces = traces if traces is not None else []
        evals = evals if evals is not None else []
        reviews = reviews if reviews is not None else []
        audits = audits if audits is not None else []
        now = now if now is not None else 10 * 86400
        dedicated = dedicated if dedicated is not None else {"month_seconds": 0, "last_24h_seconds": 0, "last_24h_cost_usd": 0}
        return CostAnomalyService(
            state_file=lambda: Path(root) / "cost-anomalies.json",
            read_traces=lambda limit=10000: traces,
            list_eval_runs=lambda limit=200: evals,
            load_dedicated_config=lambda: {},
            dedicated_runtime_cost_summary=lambda config, ts: dedicated,
            create_review_item=lambda payload: reviews.append(payload) or {"id": "review-a", **payload},
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=lambda: now,
        )

    def trace(self, ts, cost, tokens, *, model="model-a", session="session-a", actor="actor-a", route="chat", action="chat"):
        return {
            "timestamp": ts,
            "cost_usd": cost,
            "cost": {"total_tokens_est": tokens},
            "routed_model": model,
            "session_id": session,
            "actor_id": actor,
            "endpoint_mode": route,
            "action": action,
        }

    def test_detects_spend_tokens_requests_and_attributes_source(self):
        now = 10 * 86400
        baseline = [self.trace(now - 2 * 86400 - i, 1.0, 100, model="base-model", session="base-session") for i in range(7)]
        current = [
            self.trace(now - 1000 - i, 0.5, 1000, model="spike-model", session="spike-session", actor="operator-a", route="image", action="image.generate")
            for i in range(60)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp, traces=baseline + current, now=now).payload()

        metrics = {row["metric"] for row in payload["anomalies"]}
        self.assertTrue({"spend_usd", "tokens", "requests", "image_requests"}.issubset(metrics))
        spend = next(row for row in payload["anomalies"] if row["metric"] == "spend_usd")
        self.assertEqual(spend["evidence"]["top_model"]["key"], "spike-model")
        self.assertEqual(spend["evidence"]["top_session"]["key"], "spike-session")
        self.assertEqual(spend["evidence"]["top_actor"]["key"], "operator-a")
        self.assertEqual(spend["evidence"]["top_route"]["key"], "image")

    def test_suppression_and_review_are_audited(self):
        now = 10 * 86400
        traces = [self.trace(now - 100 - i, 1.0, 1000, model="spike-model") for i in range(60)]
        with tempfile.TemporaryDirectory() as tmp:
            reviews = []
            audits = []
            service = self.service(tmp, traces=traces, reviews=reviews, audits=audits, now=now)
            anomaly_id = service.payload()["anomalies"][0]["id"]
            review = service.update({"id": anomaly_id, "action": "review", "actor": {"id": "ops"}})
            updated = service.update({"id": anomaly_id, "action": "suppressed", "notes": "accepted", "actor": {"id": "ops"}})

        self.assertEqual(review["review"]["source"], {"type": "cost_anomaly", "id": anomaly_id})
        self.assertEqual(reviews[0]["reason"], "cost_anomaly")
        self.assertFalse(any(row["id"] == anomaly_id for row in updated["anomalies"]))
        self.assertEqual([entry[0][0] for entry in audits], ["cost_anomaly.review", "cost_anomaly.update"])

    def test_missing_data_returns_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp).payload()

        self.assertEqual(payload["anomalies"], [])
        self.assertEqual(payload["summary"]["count"], 0)
        self.assertEqual(payload["current"]["requests"], 0)


if __name__ == "__main__":
    unittest.main()
