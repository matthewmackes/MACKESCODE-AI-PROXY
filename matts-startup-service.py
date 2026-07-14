#!/usr/bin/env python3
"""Entry point for startup service boot hooks."""
from __future__ import annotations

import argparse
import json

from backend.v2.services.startup_services import StartupServiceManager


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Matts startup service control")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ensure-sidecars", help="start enabled proxy-owned sidecar services")
    sub.add_parser("ensure-console-runtime", help="start enabled console-owned runtime services")
    sub.add_parser("status", help="print startup service status")
    args = parser.parse_args(argv)
    manager = StartupServiceManager()
    if args.command == "ensure-sidecars":
        print(json.dumps(manager.ensure_proxy_boot_sidecars(), indent=2, sort_keys=True))
        return 0
    if args.command == "ensure-console-runtime":
        print(json.dumps(manager.ensure_console_runtime(), indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        print(json.dumps(manager.status_payload(), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
