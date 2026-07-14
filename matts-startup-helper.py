#!/usr/bin/env python3
"""Allowlisted root helper for platform systemd service management."""
from __future__ import annotations

import argparse
import subprocess
import sys


ALLOWED_UNITS = {"matts-value-set-proxy.service", "matts-console.service"}
ALLOWED_ACTIONS = {"start", "stop", "restart", "enable", "disable", "is-active", "is-enabled", "status"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action")
    parser.add_argument("unit")
    args = parser.parse_args(argv)
    if args.action not in ALLOWED_ACTIONS:
        print(f"unsupported action: {args.action}", file=sys.stderr)
        return 2
    if args.unit not in ALLOWED_UNITS:
        print(f"unit is not allowlisted: {args.unit}", file=sys.stderr)
        return 2
    result = subprocess.run(["systemctl", args.action, args.unit], text=True, check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
