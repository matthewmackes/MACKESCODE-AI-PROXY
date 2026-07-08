"""Static file serving helpers for the console HTTP handler."""
import mimetypes
from pathlib import Path


class StaticHandler:
    """Resolve safe static file responses from a fixed root directory."""

    def __init__(self, root):
        self.root = Path(root)

    def path_for(self, name):
        filename = Path(name).name
        if not filename or filename in {".", ".."}:
            raise ValueError("static filename is required")
        return self.root / filename

    def file_response(self, name, default_content_type="application/octet-stream"):
        path = self.path_for(name)
        if not path.exists() or not path.is_file():
            return None
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or default_content_type
        return {
            "status": 200,
            "data": data,
            "content_type": content_type,
            "headers": {
                "content-length": str(len(data)),
            },
        }
