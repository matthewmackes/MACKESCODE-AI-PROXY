import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.model_deprecation import ModelDeprecationService


class FakeRunStore:
    def __init__(self):
        self.profiles = [{"id": "profile-a", "name": "Profile A", "model": "old-model", "settings": {"fallback": "old-model"}}]
        self.templates = [{"id": "template-a", "name": "Template A", "body": "Use old-model carefully"}]

    def list_prompt_templates(self):
        return list(self.templates)

    def list_run_profiles(self):
        return list(self.profiles)

    def save_run_profile(self, payload):
        self.profiles = [row for row in self.profiles if row["id"] != payload["id"]]
        self.profiles.append(dict(payload))
        return payload

    def save_prompt_template(self, payload):
        self.templates = [row for row in self.templates if row["id"] != payload["id"]]
        self.templates.append(dict(payload))
        return payload


class ModelDeprecationServiceTests(unittest.TestCase):
    def service(self, tmp):
        root = Path(tmp)
        state_file = root / "model-deprecations.json"
        gateway_policy = root / "gateway-policy.json"
        gateway_policy.write_text(json.dumps({"default_model": "old-model", "fallback": "fast-model"}), encoding="utf-8")
        stores = {
            "models": [
                {"id": "old-model", "display_name": "Old Model", "type": "text", "enabled": True, "serverless": True, "access_status": "removed", "pricing": {"input": 12.0}, "last_error": "provider removed it"},
                {"id": "fast-model", "display_name": "Fast Model", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1}, "context_window": 8192},
                {"id": "image-model", "type": "image", "enabled": True, "pricing": {"image": 0.2}},
            ],
            "chats": {
                "chat-a": {"id": "chat-a", "title": "Old chat", "model": "old-model", "messages": [{"role": "assistant", "model": "old-model", "content": "ok"}]}
            },
            "datasets": {
                "dataset-a": {"schema_version": 1, "id": "dataset-a", "name": "Dataset A", "examples": [{"id": "ex-1", "input": "hi", "metadata": {"requested_model": "old-model"}}]}
            },
            "reports": {
                "report-a": {"id": "report-a", "title": "Report A", "models": ["old-model", "fast-model"], "results": [{"model": "old-model"}]}
            },
        }
        audits = []
        run_store = FakeRunStore()

        def save_models(models):
            stores["models"] = list(models)
            return stores["models"]

        service = ModelDeprecationService(
            load_model_registry=lambda include_disabled=True: list(stores["models"]),
            save_model_registry=save_models,
            refresh_model_globals=lambda: None,
            proxy_sync_payload=lambda force=False: {"in_sync": True, "force": force},
            model_scorecards_payload=lambda days=30: {"by_model": {"fast-model": {"score": 90, "confidence": "measured"}}},
            list_chats=lambda: [{"id": "chat-a", "title": "Old chat"}],
            load_chat=lambda chat_id: stores["chats"].get(chat_id),
            save_chat=lambda payload: stores["chats"].__setitem__(payload["id"], dict(payload)) or payload,
            list_eval_datasets=lambda: [{"id": "dataset-a", "name": "Dataset A"}],
            load_eval_dataset=lambda dataset_id: stores["datasets"][dataset_id],
            save_eval_dataset=lambda payload: stores["datasets"].__setitem__(payload["id"], dict(payload)) or payload,
            list_eval_runs=lambda limit=50: [{"id": "run-a", "models": ["old-model"], "summary": [{"model": "old-model"}]}],
            list_comparison_reports=lambda: [{"id": "report-a", "title": "Report A"}],
            load_comparison_report=lambda report_id: stores["reports"].get(report_id),
            save_comparison_report=lambda payload: stores["reports"].__setitem__(payload["id"], dict(payload)) or payload,
            gateway_policy_file=lambda: gateway_policy,
            state_file=lambda: state_file,
            run_store=run_store,
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=lambda: 1000.0,
        )
        return service, stores, gateway_policy, state_file, run_store, audits

    def test_detects_deprecated_model_affected_artifacts_and_recommends_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, _, _, _ = self.service(tmp)

            payload = service.payload()
            preview = service.preview({"model_id": "old-model"})

        self.assertEqual(payload["summary"]["count"], 1)
        self.assertEqual(payload["deprecated_models"][0]["status"], "removed")
        self.assertEqual(preview["replacement_model"], "fast-model")
        self.assertEqual(preview["recommendations"][0]["model"], "fast-model")
        self.assertIn("measured score 90", preview["recommendations"][0]["rationale"])
        affected_types = {item["type"] for item in preview["affected"]}
        self.assertTrue({"model_registry", "gateway_policy", "saved_chat", "eval_dataset", "eval_run", "comparison_report", "run_profile", "prompt_template"}.issubset(affected_types))
        self.assertTrue(preview["rollback"]["available_after_apply"])

    def test_apply_migration_replaces_artifacts_and_rollback_restores_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, stores, gateway_policy, state_file, run_store, audits = self.service(tmp)

            applied = service.apply({"model_id": "old-model", "replacement_model": "fast-model", "actor": {"id": "tester"}})
            migrated_models = {model["id"]: model for model in stores["models"]}
            policy_after = json.loads(gateway_policy.read_text(encoding="utf-8"))
            chat_after = dict(stores["chats"]["chat-a"])
            profile_after = dict(run_store.profiles[-1])
            template_after = dict(run_store.templates[-1])
            rollback = service.rollback({"migration_id": applied["migration"]["id"], "actor": {"id": "tester"}})
            restored_models = {model["id"]: model for model in stores["models"]}
            policy_restored = json.loads(gateway_policy.read_text(encoding="utf-8"))
            state_file_exists = state_file.exists()

        self.assertFalse(migrated_models["old-model"]["enabled"])
        self.assertEqual(migrated_models["old-model"]["deprecation"]["replacement_model"], "fast-model")
        self.assertEqual(policy_after["default_model"], "fast-model")
        self.assertEqual(chat_after["model"], "fast-model")
        self.assertEqual(profile_after["model"], "fast-model")
        self.assertIn("fast-model", template_after["body"])
        self.assertEqual(stores["chats"]["chat-a"]["model"], "old-model")
        self.assertEqual(run_store.profiles[-1]["model"], "old-model")
        self.assertIn("old-model", run_store.templates[-1]["body"])
        self.assertEqual(restored_models["old-model"]["access_status"], "removed")
        self.assertEqual(policy_restored["default_model"], "old-model")
        self.assertEqual(rollback["rolled_back"]["status"], "rolled_back")
        self.assertTrue(state_file_exists)
        self.assertEqual(audits[0][0][0], "model_deprecation.apply")
        self.assertEqual(audits[1][0][0], "model_deprecation.rollback")


if __name__ == "__main__":
    unittest.main()
