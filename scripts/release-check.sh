#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Python unit and smoke tests"
python3 -m unittest discover -s tests -v

echo "==> Python syntax checks"
python3 -m py_compile \
  image-studio.py \
  do-anthropic-proxy.py \
  matts-console.py \
  tests/test_console_smoke.py \
  tests/test_model_registry.py \
  tests/test_proxy_registry_reload.py

if command -v node >/dev/null 2>&1; then
  echo "==> Template JavaScript syntax"
  tmp_js="$(mktemp --suffix=.js)"
  trap 'rm -f "$tmp_js"' EXIT
  python3 - "$tmp_js" <<'PY'
import re
import sys
from pathlib import Path

html = Path("templates/main.html").read_text(encoding="utf-8")
scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
Path(sys.argv[1]).write_text("\n;\n".join(scripts), encoding="utf-8")
PY
  node --check "$tmp_js"
else
  echo "==> Template JavaScript syntax skipped: node is not installed"
fi

echo "Release check passed."
