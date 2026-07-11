import unittest
from types import SimpleNamespace

from src.console.services.patch_review import PatchReviewService


class PatchReviewServiceTests(unittest.TestCase):
    def runner(self, responses):
        def run(args, cwd=None):
            key = tuple(args)
            value = responses.get(key, "")
            if isinstance(value, Exception):
                return SimpleNamespace(returncode=1, stdout="", stderr=str(value))
            return SimpleNamespace(returncode=0, stdout=value, stderr="")
        return run

    def test_payload_summarizes_git_patch_and_redacts(self):
        root = "/repo"
        service = PatchReviewService(
            default_project_dir=lambda: root,
            tmux_session_items=lambda: [{"name": "work", "project_dir": root}],
            read_traces=lambda **kwargs: [{"trace_id": "trace-a", "status": "success", "action": "tmux.start"}],
            run_command=self.runner({
                ("git", "rev-parse", "--show-toplevel"): root + "\n",
                ("git", "status", "--short"): " M src/app.py\n M tests/test_app.py\n M docs/app.md\n",
                ("git", "diff", "--numstat"): "10\t2\tsrc/app.py\n3\t1\ttests/test_app.py\n1\t0\tdocs/app.md\n",
                ("git", "diff", "--unified=0", "--no-ext-diff"): "+Authorization: Bearer secret-token-value\n+new behavior\n",
            }),
            clock=lambda: 1000.0,
        )

        payload = service.payload({"session": "work"})

        self.assertEqual(payload["summary"]["changed_files"], 3)
        self.assertEqual(payload["files"][0]["area"], "src")
        self.assertIn("[redacted]", payload["diff_excerpt"])
        self.assertTrue(payload["operator_review_required"])
        self.assertIn("## Summary", payload["suggested_pr_description"])
        self.assertIn("## Risks", payload["suggested_pr_description"])
        self.assertEqual(payload["trace_links"][0]["trace_id"], "trace-a")

    def test_missing_git_repo_raises_value_error(self):
        service = PatchReviewService(
            default_project_dir=lambda: "/tmp/nope",
            run_command=self.runner({("git", "rev-parse", "--show-toplevel"): ValueError("not a git repository")}),
        )

        with self.assertRaisesRegex(ValueError, "not inside a git repository"):
            service.payload({})


if __name__ == "__main__":
    unittest.main()
