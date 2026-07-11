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

    def test_json_values_are_script_context_safe_against_breakout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "page.html").write_text("<script>let m=__META__;</script>", encoding="utf-8")
            handler = TemplateHandler(root)

            # A model id containing a closing tag / HTML comment must not break out.
            html = handler.render("page.html", {"META": {"id": "evil</script><img src=x onerror=alert(1)>"}})

        self.assertNotIn("</script><img", html)
        self.assertIn("\\u003c/script\\u003e", html)
        # Still valid: the JS parser decodes the escapes back to the real string.
        import json
        payload = html[len("<script>let m="):-len(";</script>")]
        self.assertEqual(json.loads(payload)["id"], "evil</script><img src=x onerror=alert(1)>")

    def test_script_safe_json_preserves_ordinary_whitespace(self):
        handler = TemplateHandler("/tmp")
        out = handler._script_safe_json({"name": "GPT 5 Nano"})
        self.assertIn("GPT 5 Nano", out)  # ASCII spaces untouched

    def test_template_name_must_stay_inside_template_directory(self):
        handler = TemplateHandler("/tmp")

        with self.assertRaises(ValueError):
            handler.load("../secret.txt")

        with self.assertRaises(ValueError):
            handler.load("/tmp/secret.txt")


if __name__ == "__main__":
    unittest.main()
