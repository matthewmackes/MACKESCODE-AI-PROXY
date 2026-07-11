import unittest

from src.console.services.repository_context import RepositoryContextService


class FakeConnector:
    def __init__(self, configured=True, payload=None):
        self._configured = configured
        self.payload = payload or {}

    def configured(self):
        return self._configured

    def fetch(self, ref):
        return self.payload


class RepositoryContextServiceTests(unittest.TestCase):
    def github_payload(self):
        return {
            "is_pr": True,
            "issue": {
                "title": "Fix failing tests",
                "state": "open",
                "body": "Token ghp_secretvalue should redact. See INT-064.",
                "html_url": "https://github.com/acme/app/pull/42",
                "labels": [{"name": "bug"}],
                "assignees": [{"login": "dev"}],
                "user": {"login": "author"},
                "pull_request": {},
            },
            "pull": {"head": {"sha": "abc123", "ref": "fix"}, "base": {"ref": "main"}},
            "files": [{"filename": "app.py", "status": "modified", "additions": 4, "deletions": 1, "changes": 5, "patch": "+token=secret"}],
            "checks": {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "failure", "details_url": "https://ci"}]},
            "comments": [{"user": {"login": "reviewer"}, "body": "Please fix auth.", "html_url": "https://comment"}],
            "reviews": [{"user": {"login": "lead"}, "state": "CHANGES_REQUESTED", "body": "Needs tests.", "html_url": "https://review"}],
            "review_comments": [{"user": {"login": "lead"}, "path": "app.py", "body": "Bad branch.", "html_url": "https://review-comment"}],
        }

    def test_preview_shapes_pr_context_and_redacts_tokens(self):
        service = RepositoryContextService(
            connector=FakeConnector(payload=self.github_payload()),
            worklist_text=lambda: "- INT-064 https://github.com/acme/app/pull/42\n",
            clock=lambda: 1000.0,
        )

        payload = service.preview({"reference": "https://github.com/acme/app/pull/42"})

        self.assertFalse(payload["degraded"])
        self.assertEqual(payload["context"]["kind"], "pull_request")
        self.assertEqual(payload["context"]["changed_files"][0]["filename"], "app.py")
        self.assertEqual(payload["context"]["checks"][0]["conclusion"], "failure")
        self.assertIn("Changed files", payload["prompt"])
        self.assertIn("[redacted]", payload["prompt"])
        self.assertEqual(payload["imported_context"]["head_sha"], "abc123")
        self.assertTrue(payload["context"]["linked_worklist"])

    def test_missing_token_degrades_to_reference_preview(self):
        service = RepositoryContextService(connector=FakeConnector(configured=False), clock=lambda: 1000.0)

        payload = service.preview({"reference": "acme/app#7"})

        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["reference"]["owner"], "acme")
        self.assertEqual(payload["context"]["number"], 7)
        self.assertEqual(payload["warnings"][0]["code"], "github_token_missing")

    def test_import_payload_returns_launch_patch(self):
        service = RepositoryContextService(connector=FakeConnector(payload=self.github_payload()), clock=lambda: 1000.0)

        payload = service.import_payload({"reference": "acme/app#42"})

        self.assertIn("print_prompt_append", payload["launch_patch"])
        self.assertEqual(payload["launch_patch"]["imported_context"]["repo"], "app")

    def test_invalid_reference_is_rejected(self):
        service = RepositoryContextService(connector=FakeConnector())

        with self.assertRaises(ValueError):
            service.preview({"reference": "not a reference"})


if __name__ == "__main__":
    unittest.main()
