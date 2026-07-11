"""Template loading and rendering boundary for the console UI."""
import json
from pathlib import Path


class TemplateHandler:
    """Load and render filesystem-backed HTML templates."""

    def __init__(self, template_dir):
        self.template_dir = Path(template_dir)

    def path_for(self, name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("template name must be relative to the template directory")
        return self.template_dir / relative

    def load(self, name):
        return self.path_for(name).read_text(encoding="utf-8")

    def render(self, name, replacements=None):
        html = self.load(name)
        for key, value in (replacements or {}).items():
            if not isinstance(value, str):
                value = self._script_safe_json(value)
            html = html.replace("__%s__" % key, value)
        return html

    @staticmethod
    def _script_safe_json(value):
        """JSON-encode a value for interpolation inside a <script> block.

        json.dumps alone does NOT neutralize ``</script>`` or HTML comment
        sequences, so a model id/display name containing ``</script>`` could
        close the script tag and inject markup (stored XSS). Escaping the
        HTML-significant characters (and the JS line separators U+2028/U+2029)
        as unicode escapes keeps the payload valid JSON/JS -- the JS parser turns
        ``\\u003c`` back into ``<`` -- while the HTML tokenizer never sees a
        closing tag."""
        encoded = json.dumps(value)
        return (
            encoded.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029")
        )
