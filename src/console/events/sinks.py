"""Event bus sinks."""
import json


class JsonlEventSink:
    """Append redacted event envelopes to a JSONL file."""

    def __init__(self, event_file):
        self.event_file = event_file

    def write(self, envelope):
        path = self.event_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope.to_dict(), sort_keys=True) + "\n")
