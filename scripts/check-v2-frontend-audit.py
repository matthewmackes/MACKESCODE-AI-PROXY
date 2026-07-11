#!/usr/bin/env python3
"""Fail the release gate when shipped frontend dependencies have audit findings."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"


def vulnerability_total(report: dict) -> int:
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    counts = metadata.get("vulnerabilities") if isinstance(metadata.get("vulnerabilities"), dict) else {}
    total = counts.get("total")
    if isinstance(total, int):
        return total
    vulnerabilities = report.get("vulnerabilities") if isinstance(report.get("vulnerabilities"), dict) else {}
    return len(vulnerabilities)


def vulnerability_summary(report: dict) -> str:
    vulnerabilities = report.get("vulnerabilities") if isinstance(report.get("vulnerabilities"), dict) else {}
    if not vulnerabilities:
        return "unknown production dependency vulnerability"
    parts = []
    for name, item in sorted(vulnerabilities.items()):
        severity = item.get("severity") if isinstance(item, dict) else ""
        via = item.get("via") if isinstance(item, dict) else []
        title = ""
        if isinstance(via, list):
            first = next((entry for entry in via if isinstance(entry, dict) and entry.get("title")), None)
            title = str(first.get("title")) if first else ""
        parts.append("%s%s%s" % (name, " [%s]" % severity if severity else "", ": " + title if title else ""))
    return "; ".join(parts)


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def npm_audit_report(prefix: Path) -> dict:
    if shutil.which("npm") is None:
        raise RuntimeError("npm is required for the frontend production dependency audit")
    result = subprocess.run(
        ["npm", "audit", "--omit=dev", "--json", "--prefix", str(prefix)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output = result.stdout.strip() or result.stderr.strip()
    try:
        report = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("npm audit did not return JSON: %s" % output[:400]) from exc
    if result.returncode not in (0, 1):
        raise RuntimeError("npm audit failed with exit code %s: %s" % (result.returncode, output[:400]))
    return report


def check_report(report: dict) -> tuple[bool, str]:
    total = vulnerability_total(report)
    if total:
        return False, "V2 frontend production audit failed: %d production vulnerabilit%s: %s" % (
            total,
            "y" if total == 1 else "ies",
            vulnerability_summary(report),
        )
    dependencies = (report.get("metadata") or {}).get("dependencies") if isinstance(report.get("metadata"), dict) else {}
    prod_count = dependencies.get("prod") if isinstance(dependencies, dict) else None
    suffix = " across %s production dependencies" % prod_count if isinstance(prod_count, int) else ""
    return True, "V2 frontend production audit passed: 0 production vulnerabilities%s" % suffix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default=str(FRONTEND_DIR), help="frontend package directory to audit")
    parser.add_argument("--from-file", help="read a saved npm audit JSON report instead of invoking npm")
    args = parser.parse_args(argv)

    try:
        report = load_report(Path(args.from_file)) if args.from_file else npm_audit_report(Path(args.prefix))
        ok, message = check_report(report)
    except Exception as exc:
        print("V2 frontend production audit failed: %s" % exc, file=sys.stderr)
        return 1
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
