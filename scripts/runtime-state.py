#!/usr/bin/env python3
"""Backup and restore release/runtime state for upgrades and rollback."""
import argparse
import json
import os
import shutil
import sys
import tarfile
import time
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def env_path(name, default):
    return Path(os.environ.get(name, default)).expanduser()


def default_items(include_secrets=False):
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    app_dir = env_path("MATTS_STUDIO_DIR", home / ".cache/matts-value-set/studio")
    items = [
        ("model_registry", env_path("MATTS_MODEL_CONFIG_FILE", ROOT / "config/models.json")),
        ("gateway_policy", env_path("MATTS_GATEWAY_POLICY_FILE", ROOT / "config/gateway-policy.json")),
        ("dedicated_state", env_path("MATTS_DEDICATED_CONFIG_FILE", app_dir / "dedicated-inference.json")),
        ("dedicated_events", env_path("MATTS_DEDICATED_EVENTS_FILE", app_dir / "dedicated-events.jsonl")),
        ("audit_log", env_path("MATTS_AUDIT_FILE", app_dir / "audit.jsonl")),
        ("auth_sessions", env_path("MATTS_AUTH_SESSION_FILE", app_dir / "auth-sessions.json")),
        ("serverless_catalog_cache", env_path("MATTS_SERVERLESS_CATALOG_CACHE_FILE", app_dir / "serverless-model-catalog.json")),
        ("trace_log", env_path("MATTS_TRACE_FILE", app_dir / "traces.jsonl")),
        ("tmux_registry", env_path("MATTS_TMUX_SESSION_REGISTRY_FILE", app_dir / "tmux-sessions.json")),
        ("image_history", app_dir / "history.jsonl"),
        ("images", app_dir / "images"),
        ("chats", app_dir / "chats"),
        ("eval_runs", env_path("MATTS_EVAL_RUNS_DIR", app_dir / "eval-runs")),
        ("usage_log", env_path("MATTS_VALUE_SET_COST_FILE", home / ".cache/matts-value-set/usage.jsonl")),
        ("budgets", env_path("MATTS_VALUE_SET_BUDGET_FILE", home / ".cache/matts-value-set/budgets.json")),
        ("wallpapers", env_path("MATTS_WALLPAPER_CACHE_DIR", home / ".cache/matts-value-set/wallpapers")),
    ]
    if include_secrets:
        items.extend([
            ("model_access_token", env_path("MATTS_VALUE_SET_TOKEN_FILE", home / ".mcnf-do-model-access-token")),
            ("console_auth_token", env_path("MATTS_CONSOLE_AUTH_FILE", app_dir / "console-auth-token")),
            ("digitalocean_token", env_path("DIGITALOCEAN_TOKEN_FILE", home / ".config/digitalocean/token")),
        ])
    return items


def copy_into_payload(source, dest):
    if source.is_dir():
        shutil.copytree(source, dest)
    elif source.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def backup(args):
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / (".%s.staging" % output.name)
    if staging.exists():
        shutil.rmtree(staging)
    payload = staging / "payload"
    payload.mkdir(parents=True)
    manifest = {
        "created_at": int(time.time()),
        "include_secrets": bool(args.include_secrets),
        "items": [],
    }
    for name, source in default_items(include_secrets=args.include_secrets):
        source = Path(source).expanduser()
        entry = {"name": name, "path": str(source), "exists": source.exists(), "type": "missing"}
        if source.is_dir():
            entry["type"] = "directory"
        elif source.is_file():
            entry["type"] = "file"
        if source.exists():
            dest = payload / name
            copy_into_payload(source, dest)
        manifest["items"].append(entry)
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tarfile.open(output, "w:gz") as tar:
        tar.add(staging / "manifest.json", arcname="manifest.json")
        tar.add(payload, arcname="payload")
    shutil.rmtree(staging)
    print(json.dumps({"ok": True, "archive": str(output), "items": manifest["items"]}, indent=2, sort_keys=True))
    return 0


def restore(args):
    archive = Path(args.archive).expanduser()
    staging = archive.parent / (".%s.restore" % archive.name)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        staging_root = staging.resolve()
        for member in tar.getmembers():
            target = (staging / member.name).resolve()
            if staging_root not in target.parents and target != staging_root:
                raise ValueError("Archive member escapes restore directory: %s" % member.name)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                tar.extract(member, staging)
    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    restored = []
    for entry in manifest.get("items", []):
        if not entry.get("exists"):
            continue
        src = staging / "payload" / entry["name"]
        dest = Path(entry["path"]).expanduser()
        if not src.exists():
            continue
        if dest.exists() and not args.overwrite:
            backup_path = dest.with_name(dest.name + ".pre-restore-%d" % int(time.time()))
            shutil.move(str(dest), str(backup_path))
        elif dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_into_payload(src, dest)
        restored.append({"name": entry["name"], "path": str(dest)})
    shutil.rmtree(staging)
    print(json.dumps({"ok": True, "restored": restored}, indent=2, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup", help="Create a runtime-state archive.")
    b.add_argument("--output", default="build/runtime-state-backup.tar.gz")
    b.add_argument("--include-secrets", action="store_true", help="Include token files. Store the archive securely.")
    b.set_defaults(func=backup)
    r = sub.add_parser("restore", help="Restore a runtime-state archive.")
    r.add_argument("archive")
    r.add_argument("--overwrite", action="store_true", help="Overwrite existing files instead of moving them aside.")
    r.set_defaults(func=restore)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
