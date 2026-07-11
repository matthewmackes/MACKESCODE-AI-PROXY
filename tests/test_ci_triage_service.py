import unittest

from src.console.services.ci_triage import CiTriageService
from src.console.services.failure_taxonomy import FailureTaxonomyService
from src.console.services.repository_context import RepositoryContextService
from tests.test_repository_context_service import FakeConnector


class CiTriageServiceTests(unittest.TestCase):
    def test_preview_classifies_failed_checks_and_builds_launch_patch(self):
        repo = RepositoryContextService(
            connector=FakeConnector(payload={
                "is_pr": True,
                "issue": {"title": "Fix CI", "state": "open", "html_url": "https://github.com/acme/app/pull/5", "pull_request": {}},
                "pull": {"head": {"sha": "abc", "ref": "fix"}, "base": {"ref": "main"}},
                "files": [{"filename": "tests/test_app.py", "status": "modified", "changes": 8}],
                "checks": {"check_runs": [
                    {"name": "unit", "status": "completed", "conclusion": "failure", "output": {"summary": "pytest failed with invalid JSON tool call"}},
                    {"name": "lint", "status": "completed", "conclusion": "success"},
                ]},
            }),
            clock=lambda: 1000.0,
        )
        service = CiTriageService(repository_context=repo, failure_taxonomy=FailureTaxonomyService())

        payload = service.preview({"reference": "acme/app#5"})

        self.assertEqual(payload["failure_count"], 1)
        self.assertEqual(payload["failures"][0]["name"], "unit")
        self.assertEqual(payload["failures"][0]["failure"]["category"], "malformed_tool_call")
        self.assertIn("tests/test_app.py", payload["prompt"])
        self.assertEqual(payload["launch_patch"]["imported_context"]["ci_failures"][0]["name"], "unit")

    def test_missing_token_degrades_without_failures(self):
        repo = RepositoryContextService(connector=FakeConnector(configured=False), clock=lambda: 1000.0)
        service = CiTriageService(repository_context=repo, failure_taxonomy=FailureTaxonomyService())

        payload = service.preview({"reference": "acme/app#5"})

        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["failure_count"], 0)
        self.assertIn("github_token_missing", payload["prompt"])


if __name__ == "__main__":
    unittest.main()
