#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="matts-value-set"
VERSION="${MATTS_RPM_VERSION:-2.2.0}"
TOPDIR="${MATTS_RPM_TOPDIR:-$ROOT_DIR/build/rpmbuild}"
STAGE_ROOT="$ROOT_DIR/build/rpm-stage"
SOURCE_DIR="$STAGE_ROOT/$NAME-$VERSION"
TARBALL="$TOPDIR/SOURCES/$NAME-$VERSION.tar.gz"
SPEC_SRC="$ROOT_DIR/install/matts-value-set.spec"
SPEC_DST="$TOPDIR/SPECS/matts-value-set.spec"
PIP_VENV="$STAGE_ROOT/pip-venv"

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild is required; install the rpm-build package first." >&2
  exit 1
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "python3 pip is required to vendor RPM runtime dependencies." >&2
  exit 1
fi

echo "Building V2 frontend..."
if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  npm --prefix "$ROOT_DIR/frontend" ci
fi
npm --prefix "$ROOT_DIR/frontend" run build

rm -rf "$STAGE_ROOT" "$TOPDIR"
mkdir -p "$SOURCE_DIR" "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

tar \
  --exclude='.git' \
  --exclude='.claude' \
  --exclude='.pytest_cache' \
  --exclude='build' \
  --exclude='frontend/node_modules' \
  --exclude='vendor' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -C "$ROOT_DIR" -cf - . | tar -C "$SOURCE_DIR" -xf -

echo "Vendoring pure-Python runtime dependencies..."
mkdir -p "$SOURCE_DIR/vendor/python"
python3 -m venv "$PIP_VENV"
SKIP_CYTHON=1 DISABLE_PYDANTIC_CYTHON=1 "$PIP_VENV/bin/python" -m pip install \
  --disable-pip-version-check \
  --ignore-installed \
  --no-compile \
  --no-binary pydantic,pydantic-core \
  --constraint "$SOURCE_DIR/install/requirements-rpm-constraints.txt" \
  --requirement "$SOURCE_DIR/requirements-v2.txt" \
  --target "$SOURCE_DIR/vendor/python"
rm -rf "$PIP_VENV"
rm -rf "$SOURCE_DIR/vendor/python/bin"

find "$SOURCE_DIR/vendor/python" -type d -name '__pycache__' -prune -exec rm -rf {} +

if find "$SOURCE_DIR/vendor/python" -type f -name '*.so' -print -quit | grep -q .; then
  echo "native extension found in vendored Python runtime; refusing to build noarch RPM:" >&2
  find "$SOURCE_DIR/vendor/python" -type f -name '*.so' -print >&2
  exit 1
fi

echo "Checking vendored runtime imports..."
MATTS_CONSOLE_AUTH_ENABLED=0 PYTHONPATH="$SOURCE_DIR/vendor/python:$SOURCE_DIR" python3 - <<'PY'
import fastapi
import httpx
import prompt_toolkit
import rich
import uvicorn
from backend.v2.app import create_app

create_app()
print("vendored imports ok")
PY

cp "$SPEC_SRC" "$SPEC_DST"
tar -C "$STAGE_ROOT" -czf "$TARBALL" "$NAME-$VERSION"

echo "Running rpmbuild..."
rpmbuild --define "_topdir $TOPDIR" -ba "$SPEC_DST"

echo "Built RPM artifacts:"
find "$TOPDIR/RPMS" "$TOPDIR/SRPMS" -type f -print | sort
