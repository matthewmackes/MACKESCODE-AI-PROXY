#!/usr/bin/env python3
"""Verify v2 model brand render-key coverage."""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def object_keys(source: str, name: str) -> set[str]:
    marker = re.search(r"(?:export\s+)?const\s+%s\b[^=]*=" % re.escape(name), source)
    if not marker:
        raise SystemExit("Could not find %s" % name)
    start = source.find("{", marker.end())
    if start < 0:
        raise SystemExit("Could not find %s object body" % name)
    depth = 0
    end = start
    for index, char in enumerate(source[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    body = source[start + 1:end]
    return set(re.findall(r"^\s*([A-Za-z0-9_]+)\s*:", body, flags=re.M))


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from backend.v2.services.model_showcase import BUNDLED_ARTWORK_KEYS

    brand_art = (ROOT / "frontend/src/brandMarkArt.ts").read_text(encoding="utf-8")
    model_card = (ROOT / "frontend/src/components/modelCard.tsx").read_text(encoding="utf-8")

    backend_keys = set(BUNDLED_ARTWORK_KEYS.values())
    bundled_keys = object_keys(brand_art, "BRAND_MARK_ART")
    local_keys = object_keys(model_card, "LOCAL_BRAND_MARKS")

    failures = []
    missing_bundled = sorted(backend_keys - bundled_keys)
    if missing_bundled:
        failures.append("Backend BUNDLED_ARTWORK_KEYS missing frontend SVG art: %s" % ", ".join(missing_bundled))
    missing_local = sorted(backend_keys - local_keys)
    if missing_local:
        failures.append("Backend BUNDLED_ARTWORK_KEYS missing LOCAL_BRAND_MARKS entries: %s" % ", ".join(missing_local))
    missing_local_art = sorted(local_keys - bundled_keys)
    if missing_local_art:
        failures.append("LOCAL_BRAND_MARKS entries missing bundled SVG/custom art: %s" % ", ".join(missing_local_art))

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("Brand art coverage ok: %d backend keys, %d local marks." % (len(backend_keys), len(local_keys)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
