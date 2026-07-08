import tempfile
import unittest
from pathlib import Path

from src.console.handlers.template_handler import TemplateHandler


class TemplateHandlerTests(unittest.TestCase):
    def test_render_replaces_string_and_json_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "example.html").write_text("Hello __NAME__ __ITEMS__", encoding="utf-8")
            handler = TemplateHandler(root)

            html = handler.render("example.html", {"NAME": "World", "ITEMS": ["a", "b"]})

        self.assertEqual(html, 'Hello World ["a", "b"]')

    def test_template_name_must_stay_inside_template_directory(self):
        handler = TemplateHandler("/tmp")

        with self.assertRaises(ValueError):
            handler.load("../secret.txt")

        with self.assertRaises(ValueError):
            handler.load("/tmp/secret.txt")


if __name__ == "__main__":
    unittest.main()
