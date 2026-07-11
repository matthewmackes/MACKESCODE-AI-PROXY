import tempfile
import unittest
from pathlib import Path

from src.console.services.local_rag import LocalRagService


class LocalRagServiceTests(unittest.TestCase):
    def service(self, root):
        root = Path(root)
        return LocalRagService(
            project_dir=root,
            config_file=lambda: root / ".cache" / "rag.json",
            index_file=lambda: root / ".cache" / "rag-index.json",
            clock=lambda: 1000,
        )

    def test_index_respects_include_exclude_and_runtime_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / ".cache").mkdir()
            (root / "docs" / "guide.md").write_text("Gateway routing notes\n\nUse traces for proof.", encoding="utf-8")
            (root / "docs" / "secret-token.md").write_text("token=dop_v1_should_not_index", encoding="utf-8")
            service = self.service(root)
            service.save_config({"collections": [{"id": "docs", "include": ["docs/**/*.md"], "exclude": ["docs/secret-*"]}]})

            indexed = service.index({"collection_id": "docs"})
            search = service.search({"collection_id": "docs", "query": "gateway traces"})

        self.assertEqual(indexed["indexed"][0]["files"], 1)
        self.assertEqual(search["matches"][0]["path"], "docs/guide.md")
        self.assertNotIn("secret-token", str(search))

    def test_augment_adds_cited_context_for_chat_and_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Local retrieval context for operators.", encoding="utf-8")
            service = self.service(root)
            service.index({})

            chat = service.augment({"messages": [{"role": "user", "content": "retrieval operators"}], "retrieval": {"enabled": True}}, action="chat")
            code = service.augment({"print_prompt": "Summarize retrieval", "retrieval": {"enabled": True, "query": "retrieval"}}, action="code")

        self.assertTrue(chat["retrieval"]["matches"])
        self.assertEqual(chat["data"]["messages"][0]["role"], "system")
        self.assertIn("README.md#1", chat["data"]["messages"][0]["content"])
        self.assertIn("Local retrieval context", code["data"]["print_prompt"])

    def test_empty_query_returns_no_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            result = service.search({"query": ""})

        self.assertEqual(result["matches"], [])


if __name__ == "__main__":
    unittest.main()
