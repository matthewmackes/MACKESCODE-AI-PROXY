#!/usr/bin/env python3
"""Validate that the v2 first-load React bundle does not eagerly pull Advanced chunks."""
from __future__ import annotations

from html.parser import HTMLParser
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
INDEX = DIST / "index.html"

FORBIDDEN_FIRST_LOAD_PATTERNS = (
    "antd-",
    "vendor-antd",
    "rc-",
    "xterm-",
    "ConsolePage-",
    "RunPage-",
    "ObservePage-",
    "OperatePage-",
    "TuiTerminal-",
)
REQUIRED_BOOT_FALLBACK = 'data-testid="v2-boot-fallback"'


class FirstLoadAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entry_scripts = []
        self.asset_refs = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        script_type = str(attr.get("type") or "").lower()
        rel_tokens = set(str(attr.get("rel") or "").lower().split())
        if tag == "script" and script_type == "module" and attr.get("src"):
            self.entry_scripts.append(attr["src"])
            self.asset_refs.append(attr["src"])
            return
        if tag == "link" and {"modulepreload", "stylesheet"} & rel_tokens and attr.get("href"):
            self.asset_refs.append(attr["href"])


def fail(message: str) -> int:
    print("V2 frontend bundle check failed: %s" % message, file=sys.stderr)
    return 1


def main() -> int:
    if not INDEX.exists():
        return fail("frontend/dist/index.html is missing; run npm run build first")
    html = INDEX.read_text(encoding="utf-8")
    if REQUIRED_BOOT_FALLBACK not in html:
        return fail("index.html is missing the static v2 boot fallback")
    parser = FirstLoadAssetParser()
    parser.feed(html)
    entry_matches = parser.entry_scripts
    if len(entry_matches) != 1:
        return fail("expected exactly one module entry script, found %s" % len(entry_matches))
    entry_ref = entry_matches[0].lstrip("/")
    entry_path = DIST / entry_ref
    if not entry_path.exists():
        return fail("entry chunk %s is missing" % entry_ref)
    entry = entry_path.read_text(encoding="utf-8")

    first_load_refs = [ref.lstrip("/") for ref in parser.asset_refs]
    for pattern in FORBIDDEN_FIRST_LOAD_PATTERNS:
        if any(pattern in ref for ref in first_load_refs):
            return fail("index.html eagerly references %s asset" % pattern)
        static_import = re.compile(r'import(?!\()[^;]*["\'][^"\']*%s[^"\']*["\']' % re.escape(pattern))
        if static_import.search(entry):
            return fail("entry chunk statically imports %s" % pattern)

    # Entry budget for the eager shell (drawer + Chat/Code/Research/Create +
    # Models/Advanced landing). Advanced's Console/Run/Observe/Operate tabs stay
    # lazy (enforced above). Raised modestly for the Advanced redesign.
    main_chunk_size = entry_path.stat().st_size
    if main_chunk_size > 190_000:
        return fail("entry chunk is too large for the shell: %s bytes" % main_chunk_size)

    print("V2 frontend bundle check passed: %s is %s bytes and Advanced chunks are lazy" % (entry_ref, main_chunk_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
