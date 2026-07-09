#!/usr/bin/env python3
"""Validate release health for the console and proxy services."""
import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def get_json(url, timeout):
    started = time.time()
    try:
        with urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "latency_ms": int((time.time() - started) * 1000),
                "body": json.loads(body or "{}"),
            }
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"raw": raw}
        return {"ok": False, "status": exc.code, "latency_ms": int((time.time() - started) * 1000), "body": body}
    except (OSError, URLError, ValueError) as exc:
        return {"ok": False, "status": 0, "latency_ms": int((time.time() - started) * 1000), "error": str(exc)}


def trim(url):
    return str(url or "").rstrip("/")


def validate(args):
    checks = {}
    if not args.proxy_only:
        console = trim(args.console_url)
        checks["console_health"] = get_json(console + "/health", args.timeout)
        checks["console_ready"] = get_json(console + "/ready", args.timeout)
        checks["console_version"] = get_json(console + "/version", args.timeout)
    if not args.console_only:
        proxy = trim(args.proxy_url)
        checks["proxy_capabilities"] = get_json(proxy + "/v1/claude-do/capabilities", args.timeout)
        checks["proxy_models"] = get_json(proxy + "/v1/models", args.timeout)
    ok = all(item.get("ok") for item in checks.values())
    if args.allow_degraded_console and "console_ready" in checks:
        ready = checks["console_ready"]
        if ready.get("status") == 503 and checks.get("console_health", {}).get("ok"):
            ok = all(item.get("ok") for key, item in checks.items() if key != "console_ready")
            ready["allowed_degraded"] = True
    return {"ok": ok, "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console-url", default="http://127.0.0.1:18181")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:18081")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--console-only", action="store_true")
    parser.add_argument("--proxy-only", action="store_true")
    parser.add_argument("--allow-degraded-console", action="store_true", help="Allow /ready 503 when /health is OK.")
    args = parser.parse_args(argv)
    if args.console_only and args.proxy_only:
        parser.error("--console-only and --proxy-only cannot be combined")
    result = validate(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
