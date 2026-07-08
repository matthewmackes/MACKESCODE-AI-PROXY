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
                value = json.dumps(value)
            html = html.replace("__%s__" % key, value)
        return html
